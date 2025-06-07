from flask import Flask
from flask_socketio import SocketIO, send
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('message')
def handle_message(msg):
    send(msg, broadcast=True)

@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    socketio.run(app, host="0.0.0.0", port=10000)