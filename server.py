from flask import Flask, request
from flask_socketio import SocketIO, send, emit
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

users = {}  # Зберігає нікнейми активних користувачів

@socketio.on('connect')
def handle_connect():
    users[request.sid] = "Baby😎" if len(users) == 0 else "Pink Cloud☁"
    emit("users_online", list(users.values()), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in users:
        del users[request.sid]
    emit("users_online", list(users.values()), broadcast=True)

@socketio.on('message')
def handle_message(msg):
    user = users.get(request.sid, "Unknown")
    send({"user": user, "text": msg}, broadcast=True)

@app.route('/')
def index():
    return "WebSocket сервер працює!"

@socketio.on('typing')
def handle_typing(is_typing):
    user = users.get(request.sid, "Unknown")
    emit("typing", {"user": user, "typing": is_typing}, broadcast=True, include_self=False)


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
