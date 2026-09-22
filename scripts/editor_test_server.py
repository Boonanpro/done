"""Isolated HTTP process for editor integration tests; no app startup workers."""
from fastapi import FastAPI
from app.api.editor_assistant_routes import router as assistant
from app.api.production_asset_routes import router as production

app = FastAPI()
app.include_router(assistant, prefix='/api/v1')
app.include_router(production, prefix='/api/v1')

@app.get('/health')
def health():
    return {'status': 'healthy', 'service': 'isolated-editor-test'}
