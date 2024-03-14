def add_system_prompt_safe(body, custom_content="Sample Content"):
    try:
        import json
        
        # Check if body is a bytes object, if so, decode it
        if isinstance(body, bytes):
            body = body.decode('utf-8')
        
        # Convert string to dictionary if necessary
        if isinstance(body, str):
            body = json.loads(body)
        
        # Proceed only if body is a dictionary and has 'messages'
        if isinstance(body, dict) and 'messages' in body:
            messages = body['messages']
            new_message = {"role": "system", "content": custom_content}
            messages.insert(0, new_message)
            body['messages'] = messages
            
        # Convert the dictionary back to JSON and encode to bytes before returning
        return json.dumps(body).encode('utf-8')
    
    except Exception as e:
        # In case of any error, return the input as it is
        if isinstance(body, dict):
            return json.dumps(body).encode('utf-8')  # Return as bytes if input was initially a dict
        elif isinstance(body, bytes):
            return body  # Return original bytes object
        elif isinstance(body, str):
            return body.encode('utf-8')  # Return as bytes if input was initially a string
        else:
            return str(body).encode('utf-8')  # Return string representation of the input encoded as bytes if it's neither


# Test the function with different scenarios
custom_message = "Custom System Message"

sample_body_correct = b'{"model":"zephyr:7b-beta-q5_K_M","messages":[{"role":"user","content":"Help me with my nutrition plan please."},{"role":"assistant","content":""}],"options":{}}'

sample_body_str = '{"model":"zephyr:7b-beta-q5_K_M","messages":[{"role":"user","content":"Help me with my nutrition plan please."},{"role":"assistant","content":""}],"options":{}}'
sample_body_error = "Not a JSON"

# Call the function with different types of inputs
result_correct = add_system_prompt_safe(sample_body_correct, custom_message)
result_str = add_system_prompt_safe(sample_body_str, custom_message)
# result_error = add_system_prompt_safe(sample_body_error)

print(sample_body_correct)
print("\n")
print(result_correct)
print("\n")
print("\n")
print(sample_body_str)
print("\n")
print(result_str)
# print(result_error)
