import json
from flask import Flask, request
from flask_socketio import SocketIO, send
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('message')
def handle_message(msg):
    user = "Baby" if request.sid == list(socketio.server.eio.sockets.keys())[0] else "Pink Cloud"
    send(json.dumps({"user": user, "text": msg}), broadcast=True)

@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
