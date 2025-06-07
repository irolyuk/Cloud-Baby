from flask import Flask, request
from flask_socketio import SocketIO, send
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

users = {}  # Зберігає нікнейм кожного користувача

@socketio.on('connect')
def handle_connect():
    users[request.sid] = "Baby😎" if len(users) == 0 else "Pink Cloud❤"
    print(f"Користувач {users[request.sid]} підключився ({request.sid})")

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in users:
        del users[request.sid]
    print(f"Користувач {request.sid} відключився")

@socketio.on('message')
def handle_message(msg):
    user = users.get(request.sid, "Unknown")
    send({"user": user, "text": msg}, broadcast=True)

@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
