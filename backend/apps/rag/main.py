from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
import os, shutil

from pathlib import Path
from typing import List

from sentence_transformers import SentenceTransformer
from chromadb.utils import embedding_functions

from langchain_community.document_loaders import (
    WebBaseLoader,
    TextLoader,
    PyPDFLoader,
    CSVLoader,
    Docx2txtLoader,
    UnstructuredEPubLoader,
    UnstructuredWordDocumentLoader,
    UnstructuredMarkdownLoader,
    UnstructuredXMLLoader,
    UnstructuredRSTLoader,
    UnstructuredExcelLoader,
)
from langchain.text_splitter import RecursiveCharacterTextSplitter

from pydantic import BaseModel
from typing import Optional
import mimetypes
import uuid
import json


from apps.web.models.documents import (
    Documents,
    DocumentForm,
    DocumentResponse,
)

from utils.misc import (
    calculate_sha256,
    calculate_sha256_string,
    sanitize_filename,
    extract_folders_after_data_docs,
)
from utils.utils import get_current_user, get_admin_user
from config import (
    UPLOAD_DIR,
    DOCS_DIR,
    RAG_EMBEDDING_MODEL,
    RAG_EMBEDDING_MODEL_DEVICE_TYPE,
    CHROMA_CLIENT,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    RAG_TEMPLATE,
)

from constants import ERROR_MESSAGES

#
# if RAG_EMBEDDING_MODEL:
#    sentence_transformer_ef = SentenceTransformer(
#        model_name_or_path=RAG_EMBEDDING_MODEL,
#        cache_folder=RAG_EMBEDDING_MODEL_DIR,
#        device=RAG_EMBEDDING_MODEL_DEVICE_TYPE,
#    )


app = FastAPI()

app.state.CHUNK_SIZE = CHUNK_SIZE
app.state.CHUNK_OVERLAP = CHUNK_OVERLAP
app.state.RAG_TEMPLATE = RAG_TEMPLATE
app.state.RAG_EMBEDDING_MODEL = RAG_EMBEDDING_MODEL
app.state.TOP_K = 4

app.state.sentence_transformer_ef = (
    embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=app.state.RAG_EMBEDDING_MODEL,
        device=RAG_EMBEDDING_MODEL_DEVICE_TYPE,
    )
)


origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CollectionNameForm(BaseModel):
    collection_name: Optional[str] = "test"


class StoreWebForm(CollectionNameForm):
    url: str


def store_data_in_vector_db(data, collection_name) -> bool:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=app.state.CHUNK_SIZE, chunk_overlap=app.state.CHUNK_OVERLAP
    )
    docs = text_splitter.split_documents(data)

    texts = [doc.page_content for doc in docs]
    metadatas = [doc.metadata for doc in docs]

    try:
        collection = CHROMA_CLIENT.create_collection(
            name=collection_name,
            embedding_function=app.state.sentence_transformer_ef,
        )

        collection.add(
            documents=texts, metadatas=metadatas, ids=[str(uuid.uuid1()) for _ in texts]
        )
        return True
    except Exception as e:
        print(e)
        if e.__class__.__name__ == "UniqueConstraintError":
            return True

        return False


@app.get("/")
async def get_status():
    return {
        "status": True,
        "chunk_size": app.state.CHUNK_SIZE,
        "chunk_overlap": app.state.CHUNK_OVERLAP,
        "template": app.state.RAG_TEMPLATE,
        "embedding_model": app.state.RAG_EMBEDDING_MODEL,
    }


@app.get("/embedding/model")
async def get_embedding_model(user=Depends(get_admin_user)):
    return {
        "status": True,
        "embedding_model": app.state.RAG_EMBEDDING_MODEL,
    }


class EmbeddingModelUpdateForm(BaseModel):
    embedding_model: str


@app.post("/embedding/model/update")
async def update_embedding_model(
    form_data: EmbeddingModelUpdateForm, user=Depends(get_admin_user)
):
    app.state.RAG_EMBEDDING_MODEL = form_data.embedding_model
    app.state.sentence_transformer_ef = (
        embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=app.state.RAG_EMBEDDING_MODEL,
            device=RAG_EMBEDDING_MODEL_DEVICE_TYPE,
        )
    )

    return {
        "status": True,
        "embedding_model": app.state.RAG_EMBEDDING_MODEL,
    }


@app.get("/chunk")
async def get_chunk_params(user=Depends(get_admin_user)):
    return {
        "status": True,
        "chunk_size": app.state.CHUNK_SIZE,
        "chunk_overlap": app.state.CHUNK_OVERLAP,
    }


class ChunkParamUpdateForm(BaseModel):
    chunk_size: int
    chunk_overlap: int


@app.post("/chunk/update")
async def update_chunk_params(
    form_data: ChunkParamUpdateForm, user=Depends(get_admin_user)
):
    app.state.CHUNK_SIZE = form_data.chunk_size
    app.state.CHUNK_OVERLAP = form_data.chunk_overlap

    return {
        "status": True,
        "chunk_size": app.state.CHUNK_SIZE,
        "chunk_overlap": app.state.CHUNK_OVERLAP,
    }


@app.get("/template")
async def get_rag_template(user=Depends(get_current_user)):
    return {
        "status": True,
        "template": app.state.RAG_TEMPLATE,
    }


@app.get("/query/settings")
async def get_query_settings(user=Depends(get_admin_user)):
    return {
        "status": True,
        "template": app.state.RAG_TEMPLATE,
        "k": app.state.TOP_K,
    }


class QuerySettingsForm(BaseModel):
    k: Optional[int] = None
    template: Optional[str] = None


@app.post("/query/settings/update")
async def update_query_settings(
    form_data: QuerySettingsForm, user=Depends(get_admin_user)
):
    app.state.RAG_TEMPLATE = form_data.template if form_data.template else RAG_TEMPLATE
    app.state.TOP_K = form_data.k if form_data.k else 4
    return {"status": True, "template": app.state.RAG_TEMPLATE}


class QueryDocForm(BaseModel):
    collection_name: str
    query: str
    k: Optional[int] = None


@app.post("/query/doc")
def query_doc(
    form_data: QueryDocForm,
    user=Depends(get_current_user),
):
    try:
        # if you use docker use the model from the environment variable
        collection = CHROMA_CLIENT.get_collection(
            name=form_data.collection_name,
            embedding_function=app.state.sentence_transformer_ef,
        )
        result = collection.query(
            query_texts=[form_data.query],
            n_results=form_data.k if form_data.k else app.state.TOP_K,
        )
        return result
    except Exception as e:
        print(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


class QueryCollectionsForm(BaseModel):
    collection_names: List[str]
    query: str
    k: Optional[int] = None


def merge_and_sort_query_results(query_results, k):
    # Initialize lists to store combined data
    combined_ids = []
    combined_distances = []
    combined_metadatas = []
    combined_documents = []

    # Combine data from each dictionary
    for data in query_results:
        combined_ids.extend(data["ids"][0])
        combined_distances.extend(data["distances"][0])
        combined_metadatas.extend(data["metadatas"][0])
        combined_documents.extend(data["documents"][0])

    # Create a list of tuples (distance, id, metadata, document)
    combined = list(
        zip(combined_distances, combined_ids, combined_metadatas, combined_documents)
    )

    # Sort the list based on distances
    combined.sort(key=lambda x: x[0])

    # Unzip the sorted list
    sorted_distances, sorted_ids, sorted_metadatas, sorted_documents = zip(*combined)

    # Slicing the lists to include only k elements
    sorted_distances = list(sorted_distances)[:k]
    sorted_ids = list(sorted_ids)[:k]
    sorted_metadatas = list(sorted_metadatas)[:k]
    sorted_documents = list(sorted_documents)[:k]

    # Create the output dictionary
    merged_query_results = {
        "ids": [sorted_ids],
        "distances": [sorted_distances],
        "metadatas": [sorted_metadatas],
        "documents": [sorted_documents],
        "embeddings": None,
        "uris": None,
        "data": None,
    }

    return merged_query_results


@app.post("/query/collection")
def query_collection(
    form_data: QueryCollectionsForm,
    user=Depends(get_current_user),
):
    results = []

    for collection_name in form_data.collection_names:
        try:
            # if you use docker use the model from the environment variable
            collection = CHROMA_CLIENT.get_collection(
                name=collection_name,
                embedding_function=app.state.sentence_transformer_ef,
            )

            result = collection.query(
                query_texts=[form_data.query],
                n_results=form_data.k if form_data.k else app.state.TOP_K,
            )
            results.append(result)
        except:
            pass

    return merge_and_sort_query_results(
        results, form_data.k if form_data.k else app.state.TOP_K
    )


@app.post("/web")
def store_web(form_data: StoreWebForm, user=Depends(get_current_user)):
    # "https://www.gutenberg.org/files/1727/1727-h/1727-h.htm"
    try:
        loader = WebBaseLoader(form_data.url)
        data = loader.load()

        collection_name = form_data.collection_name
        if collection_name == "":
            collection_name = calculate_sha256_string(form_data.url)[:63]

        store_data_in_vector_db(data, collection_name)
        return {
            "status": True,
            "collection_name": collection_name,
            "filename": form_data.url,
        }
    except Exception as e:
        print(e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(e),
        )


def get_loader(filename: str, file_content_type: str, file_path: str):
    file_ext = filename.split(".")[-1].lower()
    known_type = True

    known_source_ext = [
        "go",
        "py",
        "java",
        "sh",
        "bat",
        "ps1",
        "cmd",
        "js",
        "ts",
        "css",
        "cpp",
        "hpp",
        "h",
        "c",
        "cs",
        "sql",
        "log",
        "ini",
        "pl",
        "pm",
        "r",
        "dart",
        "dockerfile",
        "env",
        "php",
        "hs",
        "hsc",
        "lua",
        "nginxconf",
        "conf",
        "m",
        "mm",
        "plsql",
        "perl",
        "rb",
        "rs",
        "db2",
        "scala",
        "bash",
        "swift",
        "vue",
        "svelte",
    ]

    if file_ext == "pdf":
        loader = PyPDFLoader(file_path)
    elif file_ext == "csv":
        loader = CSVLoader(file_path)
    elif file_ext == "rst":
        loader = UnstructuredRSTLoader(file_path, mode="elements")
    elif file_ext == "xml":
        loader = UnstructuredXMLLoader(file_path)
    elif file_ext == "md":
        loader = UnstructuredMarkdownLoader(file_path)
    elif file_content_type == "application/epub+zip":
        loader = UnstructuredEPubLoader(file_path)
    elif (
        file_content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or file_ext in ["doc", "docx"]
    ):
        loader = Docx2txtLoader(file_path)
    elif file_content_type in [
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ] or file_ext in ["xls", "xlsx"]:
        loader = UnstructuredExcelLoader(file_path)
    elif file_ext in known_source_ext or (
        file_content_type and file_content_type.find("text/") >= 0
    ):
        loader = TextLoader(file_path)
    else:
        loader = TextLoader(file_path)
        known_type = False

    # return loader, known_type
        
    # HOTFIX: Inject Pebblo
    from langchain_community.document_loaders.pebblo import PebbloSafeLoader
    return PebbloSafeLoader(loader, name="pebblo_demo"), known_type
    # HOTFIX: END CODE INJECTION


@app.post("/doc")
def store_doc(
    collection_name: Optional[str] = Form(None),
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    # "https://www.gutenberg.org/files/1727/1727-h/1727-h.htm"

    print(file.content_type)
    try:
        filename = file.filename
        file_path = f"{UPLOAD_DIR}/{filename}"
        contents = file.file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
            f.close()

        f = open(file_path, "rb")
        if collection_name == None:
            collection_name = calculate_sha256(f)[:63]
        f.close()

        loader, known_type = get_loader(file.filename, file.content_type, file_path)
        data = loader.load()
        result = store_data_in_vector_db(data, collection_name)

        if result:
            return {
                "status": True,
                "collection_name": collection_name,
                "filename": filename,
                "known_type": known_type,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=ERROR_MESSAGES.DEFAULT(),
            )
    except Exception as e:
        print(e)
        if "No pandoc was found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.PANDOC_NOT_INSTALLED,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT(e),
            )


@app.get("/scan")
def scan_docs_dir(user=Depends(get_admin_user)):
    for path in Path(DOCS_DIR).rglob("./**/*"):
        try:
            if path.is_file() and not path.name.startswith("."):
                tags = extract_folders_after_data_docs(path)
                filename = path.name
                file_content_type = mimetypes.guess_type(path)

                f = open(path, "rb")
                collection_name = calculate_sha256(f)[:63]
                f.close()

                loader, known_type = get_loader(
                    filename, file_content_type[0], str(path)
                )
                data = loader.load()

                result = store_data_in_vector_db(data, collection_name)

                if result:
                    sanitized_filename = sanitize_filename(filename)
                    doc = Documents.get_doc_by_name(sanitized_filename)

                    if doc == None:
                        doc = Documents.insert_new_doc(
                            user.id,
                            DocumentForm(
                                **{
                                    "name": sanitized_filename,
                                    "title": filename,
                                    "collection_name": collection_name,
                                    "filename": filename,
                                    "content": (
                                        json.dumps(
                                            {
                                                "tags": list(
                                                    map(
                                                        lambda name: {"name": name},
                                                        tags,
                                                    )
                                                )
                                            }
                                        )
                                        if len(tags)
                                        else "{}"
                                    ),
                                }
                            ),
                        )

        except Exception as e:
            print(e)

    return True


@app.get("/reset/db")
def reset_vector_db(user=Depends(get_admin_user)):
    CHROMA_CLIENT.reset()


@app.get("/reset")
def reset(user=Depends(get_admin_user)) -> bool:
    folder = f"{UPLOAD_DIR}"
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print("Failed to delete %s. Reason: %s" % (file_path, e))

    try:
        CHROMA_CLIENT.reset()
    except Exception as e:
        print(e)

    return True
