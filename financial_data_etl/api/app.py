from fastapi import FastAPI

app = FastAPI(title="financial-data-etl api")

@app.get("/")
def root():
    return {"status": "api ok"}