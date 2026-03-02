from fastapi import FastAPI, Request, Response, HTTPException
import redis
import sqlite3
import secrets
import bcrypt
import json
import time

app = FastAPI()


# Redis для сессий

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
SESSION_TTL = 60 * 60 * 24  


def get_connection():
    conn = sqlite3.connect("app.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


init_db()



# Сессии

def generate_token():
    return secrets.token_hex(32)


def create_session(user_id=None):
    token = generate_token()
    session_data = {
        "user_id": user_id,
        "authenticated": bool(user_id),
        "created_at": time.time(),
        "history": []
    }
    r.setex(token, SESSION_TTL, json.dumps(session_data))
    return token


def get_session(token):
    data = r.get(token)
    if not data:
        return None
    return json.loads(data)


def save_session(token, session_data):
    r.setex(token, SESSION_TTL, json.dumps(session_data))


def delete_session(token):
    r.delete(token)



# register

@app.post("/register")
async def register(request: Request):
    data = await request.json()
    email = data["email"]
    password = data["password"]

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, password_hash)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="User already exists")

    conn.close()
    return {"message": "User created"}


# LOGIN

@app.post("/login")
async def login(request: Request, response: Response):
    data = await request.json()
    email = data["email"]
    password = data["password"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, password_hash FROM users WHERE email = ?",
        (email,)
    )
    user = cur.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401)

    user_id = user["id"]
    password_hash = user["password_hash"]

    if not bcrypt.checkpw(password.encode(), password_hash.encode()):
        raise HTTPException(status_code=401)

    # защита от session fixation
    old_token = request.cookies.get("session_token")
    if old_token:
        delete_session(old_token)

    token = create_session(user_id)

    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=False,  # True на продакшене (HTTPS)
        samesite="Lax"
    )

    return {"message": "Logged in"}


# logout

@app.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        delete_session(token)
    response.delete_cookie("session_token")
    return {"message": "Logged out"}


# chat

@app.post("/chat")
async def chat(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401)

    session = get_session(token)
    if not session or not session["authenticated"]:
        raise HTTPException(status_code=403)

    data = await request.json()
    message = data.get("message", "")

    session["history"].append({"role": "user", "content": message})

    ai_reply = f"Ответ по теме: {message}"
    session["history"].append({"role": "assistant", "content": ai_reply})

    save_session(token, session)

    return {"reply": ai_reply}