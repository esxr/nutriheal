from fastapi import FastAPI, Request, Response, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool

import requests
import json
import uuid
from pydantic import BaseModel

from apps.web.models.users import Users
from constants import ERROR_MESSAGES
from utils.utils import decode_token, get_current_user, get_admin_user
from config import OLLAMA_BASE_URL, WEBUI_AUTH

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.OLLAMA_BASE_URL = OLLAMA_BASE_URL

# TARGET_SERVER_URL = OLLAMA_API_BASE_URL


REQUEST_POOL = []


@app.get("/url")
async def get_ollama_api_url(user=Depends(get_admin_user)):
    return {"OLLAMA_BASE_URL": app.state.OLLAMA_BASE_URL}


class UrlUpdateForm(BaseModel):
    url: str


@app.post("/url/update")
async def update_ollama_api_url(form_data: UrlUpdateForm, user=Depends(get_admin_user)):
    app.state.OLLAMA_BASE_URL = form_data.url
    return {"OLLAMA_BASE_URL": app.state.OLLAMA_BASE_URL}


@app.get("/cancel/{request_id}")
async def cancel_ollama_request(request_id: str, user=Depends(get_current_user)):
    if user:
        if request_id in REQUEST_POOL:
            REQUEST_POOL.remove(request_id)
        return True
    else:
        raise HTTPException(status_code=401, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)


# HOTFIX: FUNCTIONS FOR ADDING PROMPT ENGINEERING TO BODY
def add_system_prompt(body, custom_content="Sample Content"):
    try:
        import json

        # Check if body is a bytes object, if so, decode it
        if isinstance(body, bytes):
            body = body.decode("utf-8")

        # Convert string to dictionary if necessary
        if isinstance(body, str):
            body = json.loads(body)

        # Proceed only if body is a dictionary and has 'messages'
        if isinstance(body, dict) and "messages" in body:
            messages = body["messages"]
            new_message = {"role": "system", "content": custom_content}
            messages.insert(0, new_message)
            body["messages"] = messages

        # Convert the dictionary back to JSON and encode to bytes before returning
        return json.dumps(body).encode("utf-8")

    except Exception as e:
        # In case of any error, return the input as it is
        if isinstance(body, dict):
            return json.dumps(body).encode(
                "utf-8"
            )  # Return as bytes if input was initially a dict
        elif isinstance(body, bytes):
            return body  # Return original bytes object
        elif isinstance(body, str):
            return body.encode(
                "utf-8"
            )  # Return as bytes if input was initially a string
        else:
            return str(body).encode(
                "utf-8"
            )  # Return string representation of the input encoded as bytes if it's neither


def add_prefix_to_user_messages(body, prefix="Sample Prefix: "):
    try:
        import json

        # Check if body is a bytes object, if so, decode it
        if isinstance(body, bytes):
            body = body.decode("utf-8")

        # Convert string to dictionary if necessary
        if isinstance(body, str):
            body = json.loads(body)

        # Proceed only if body is a dictionary and has 'messages'
        if isinstance(body, dict) and "messages" in body:
            for message in body["messages"]:
                # Check if the message is from a user and prepend the prefix
                if message.get("role") == "user":
                    message["content"] = prefix + message["content"]

        # Convert the dictionary back to JSON and encode to bytes before returning
        return json.dumps(body).encode("utf-8")

    except Exception as e:
        # In case of any error, return the input as it is
        if isinstance(body, dict):
            return json.dumps(body).encode(
                "utf-8"
            )  # Return as bytes if input was initially a dict
        elif isinstance(body, bytes):
            return body  # Return original bytes object
        elif isinstance(body, str):
            return body.encode(
                "utf-8"
            )  # Return as bytes if input was initially a string
        else:
            return str(body).encode(
                "utf-8"
            )  # Return string representation of the input encoded as bytes if it's neither


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request, user=Depends(get_current_user)):
    target_url = f"{app.state.OLLAMA_BASE_URL}/{path}"

    body = await request.body()

    # HOTFIX: ADD PROMPT ENGINEERING TO BODY
    custom_system_prompt = """
You are designed exclusively for creating personalized nutrition plans for patients based on their specific health conditions and dietary needs. Upon receiving a patient's data, including their health conditions, allergies, and dietary preferences, you will generate a balanced diet plan tailored to their requirements. You should STRICTLY adhere to the following strict guidelines:
I REPEAT - STRICTLY ADHERE TO THE FOLLOWING GUIDELINES:
- IMPORTANT: You should only respond to requests related to creating personalized nutrition plans. 
- IMPORTANT: If asked about any other topic, you must explicitly REFUSE to ANSWER, stating that responding to such queries is against your policy
- If the necessary patient data is not provided in the request, you WILL ASK for this data before proceeding.
- You will NEVER make assumptions or deductions without receiving specific patient data. This is to ensure the safety and well-being of the patients involved.

By adhering to these guidelines, you should ensure that you provide accurate, safe, and legally compliant dietary recommendations to patients.
"""

    custom_user_prefix = """
I'll tell you the following about myself, please say "This is off-topic" if this is out of your domain, else respond to my queries.
"""

    body = add_system_prompt(body, custom_system_prompt)
    body = add_prefix_to_user_messages(body, custom_user_prefix)

    headers = dict(request.headers)

    if user.role in ["user", "admin"]:
        if path in ["pull", "delete", "push", "copy", "create"]:
            if user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
                )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    headers.pop("host", None)
    headers.pop("authorization", None)
    headers.pop("origin", None)
    headers.pop("referer", None)

    r = None

    def get_request():
        nonlocal r

        request_id = str(uuid.uuid4())
        try:
            REQUEST_POOL.append(request_id)

            def stream_content():
                try:
                    if path == "generate":
                        data = json.loads(body.decode("utf-8"))

                        if not ("stream" in data and data["stream"] == False):
                            yield json.dumps({"id": request_id, "done": False}) + "\n"

                    elif path == "chat":
                        yield json.dumps({"id": request_id, "done": False}) + "\n"

                    for chunk in r.iter_content(chunk_size=8192):
                        if request_id in REQUEST_POOL:
                            yield chunk
                        else:
                            print("User: canceled request")
                            break
                finally:
                    if hasattr(r, "close"):
                        r.close()
                        if request_id in REQUEST_POOL:
                            REQUEST_POOL.remove(request_id)

            r = requests.request(
                method=request.method,
                url=target_url,
                data=body,
                headers=headers,
                stream=True,
            )

            r.raise_for_status()

            # r.close()

            return StreamingResponse(
                stream_content(),
                status_code=r.status_code,
                headers=dict(r.headers),
            )
        except Exception as e:
            raise e

    try:
        return await run_in_threadpool(get_request)
    except Exception as e:
        error_detail = "Open WebUI: Server Connection Error"
        if r is not None:
            try:
                res = r.json()
                if "error" in res:
                    error_detail = f"Ollama: {res['error']}"
            except:
                error_detail = f"Ollama: {e}"

        raise HTTPException(
            status_code=r.status_code if r else 500,
            detail=error_detail,
        )
