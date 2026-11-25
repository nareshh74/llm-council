"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import otel_lite
from . import storage
from . import knowledge
from .workspace import open_workspace, resolve_folder, browse
from . import diagrams
from . import activity
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings

app = FastAPI(title="LLM Council API")
otel_lite.init("llm-council")
otel_lite.install_log_correlation()
app.add_middleware(otel_lite.TraceMiddleware)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    folder: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    folder: Optional[str] = None
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    folder: Optional[str] = None
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    folder = None
    if request.folder:
        try:
            folder = resolve_folder(request.folder)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    conversation = storage.create_conversation(conversation_id, folder)
    return conversation


class SetFolderRequest(BaseModel):
    """Set (or clear, with null) the folder of a conversation that has no messages yet."""
    folder: Optional[str] = None


@app.get("/api/diagrams/{diagram_id}")
async def get_diagram(diagram_id: str):
    """Serve a diagram the council drew, as a standalone HTML page."""
    try:
        path = diagrams.path_for(diagram_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Diagram not found")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Diagram not found")
    return FileResponse(path, media_type="text/html")


@app.get("/api/browse")
async def browse_folders(path: str = ""):
    """List subfolders for the folder picker, limited to the allowed roots."""
    try:
        return browse(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/conversations/{conversation_id}/folder", response_model=Conversation)
async def set_conversation_folder(conversation_id: str, request: SetFolderRequest):
    """Choose the folder a conversation runs in. Only allowed before the first message."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation["messages"]:
        raise HTTPException(status_code=409, detail="Folder can only be changed before the first message")
    try:
        conversation["folder"] = resolve_folder(request.folder) if request.folder else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    storage.save_conversation(conversation)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process
    async with open_workspace(conversation.get("folder") or ""):
        stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
            knowledge.augment(request.content), conversation["messages"]
        )
    knowledge.save(request.content, stage3_result)

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        sink = activity.Sink()

        async def pipeline():
            activity.sink.set(sink)
            try:
                storage.add_user_message(conversation_id, request.content)

                title_task = None
                if is_first_message:
                    token = activity.stage.set("title")
                    title_task = asyncio.create_task(generate_conversation_title(request.content))
                    activity.stage.reset(token)

                activity.stage.set("stage1")
                sink.put({'type': 'stage1_start'})
                activity.stage.set("memory")
                mem_id = activity.new_id()
                activity.emit("memory", id=mem_id, status="running")
                query = await asyncio.to_thread(knowledge.augment, request.content)
                activity.emit("memory", id=mem_id, status="done", chars=max(len(query) - len(request.content), 0))

                activity.stage.set("stage1")
                async with open_workspace(conversation.get("folder") or "") as ws:
                    if ws:
                        activity.emit("workspace", folder=ws.root.name, tools=len(ws.mcp), skills=len(ws.skills))
                    stage1_results = await stage1_collect_responses(query, conversation["messages"])
                sink.put({'type': 'stage1_complete', 'data': stage1_results})

                activity.stage.set("stage2")
                sink.put({'type': 'stage2_start'})
                stage2_results, label_to_model = await stage2_collect_rankings(query, stage1_results, conversation["messages"])
                aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
                sink.put({'type': 'stage2_complete', 'data': stage2_results,
                          'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})

                activity.stage.set("stage3")
                sink.put({'type': 'stage3_start'})
                stage3_result = await stage3_synthesize_final(query, stage1_results, stage2_results, conversation["messages"])
                activity.stage.set("memory")
                save_id = activity.new_id()
                activity.emit("memory_save", id=save_id, status="running")
                await asyncio.to_thread(knowledge.save, request.content, stage3_result)
                activity.emit("memory_save", id=save_id, status="done")
                sink.put({'type': 'stage3_complete', 'data': stage3_result})

                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title)
                    activity.stage.set("title")
                    activity.emit("title", title=title)
                    sink.put({'type': 'title_complete', 'data': {'title': title}})

                storage.add_assistant_message(
                    conversation_id,
                    stage1_results,
                    stage2_results,
                    stage3_result,
                    sink.log
                )
                sink.put({'type': 'complete'})
            except Exception as e:
                sink.put({'type': 'error', 'message': str(e)})
            finally:
                sink.queue.put_nowait(None)

        task = asyncio.create_task(pipeline())
        try:
            while True:
                event = await sink.queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
