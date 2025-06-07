from flask import Flask
from flask_socketio import SocketIO, send
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

@socketio.on('message')
def handle_message(msg):
    send(msg, broadcast=True)

@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    import os
    import eventlet
    eventlet.monkey_patch()

    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
