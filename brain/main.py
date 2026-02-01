from fastapi import FastAPI
from pydantic import BaseModel
from ollama_client import chat

app = FastAPI(title="Voice Assistant Brain")


class AskRequest(BaseModel):
    text: str


class AskResponse(BaseModel):
    response: str


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    """Process a voice query and return a response."""
    response_text = chat(request.text)
    return AskResponse(response=response_text)


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}
