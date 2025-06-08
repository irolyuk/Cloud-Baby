from flask import Flask, request # type: ignore
from flask_socketio import SocketIO, send, emit # type: ignore
from flask_cors import CORS # type: ignore

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

users = {}  # Зберігає нікнейми активних користувачів
history = []

@socketio.on('connect')
def handle_connect():
    pass  # Очікуємо нікнейм окремо

@socketio.on('register')
def handle_register(nickname):
    users[request.sid] = nickname
    emit("users_online", list(users.values()), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in users:
        del users[request.sid]
    emit("users_online", list(users.values()), broadcast=True)

@socketio.on('message')
def handle_message(msg):
    # Тепер 'msg' - це об'єкт: { type: 'text'/'image', text: '...', image: '...' }
    user = users.get(request.sid, "Unknown")
    
    # Створюємо об'єкт повідомлення для збереження та відправки
    message_data = {
        "user": user,
        "type": msg.get('type', 'text'), # Тип повідомлення, за замовчуванням 'text'
        "text": msg.get('text'),         # Текст, буде None для зображень
        "image": msg.get('image')        # Дані зображення, будуть None для тексту
    }
    
    history.append(message_data)
    if len(history) > 50:
        history.pop(0)
    emit('message', message_data, broadcast=True) # Використовуємо emit з подією 'message'

@socketio.on('get_history')
def handle_history():
    emit("chat_history", history)

@socketio.on('typing')
def handle_typing(is_typing):
    user = users.get(request.sid, "Unknown")
    emit("typing", {"user": user, "typing": is_typing}, broadcast=True, include_self=False)

@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
