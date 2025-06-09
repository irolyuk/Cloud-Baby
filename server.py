from flask import Flask, request # type: ignore
from flask_socketio import SocketIO, send, emit # type: ignore
from flask_cors import CORS # type: ignore
import uuid # Для генерації унікальних ID

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10 * 1024 * 1024) # Збільшуємо до 10MB

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
    user_sid = request.sid
    user = users.get(user_sid, "Unknown")
    
    # Створюємо об'єкт повідомлення для збереження та відправки
    message_data = {
        "messageId": str(uuid.uuid4()), # Генеруємо унікальний ID для повідомлення
        "user": user,
        "type": msg.get('type', 'text'), # Тип повідомлення, за замовчуванням 'text'
        "text": msg.get('text'),         # Текст
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

@socketio.on('delete_message')
def handle_delete_message(data):
    message_id_to_delete = data.get('messageId')
    user_sid = request.sid
    requesting_user = users.get(user_sid)

    global history
    message_found = False
    for message in history:
        if message.get('messageId') == message_id_to_delete:
            # Перевірка, чи користувач, який видаляє, є автором повідомлення
            if message.get('user') == requesting_user:
                history.remove(message)
                emit('message_deleted', {'messageId': message_id_to_delete}, broadcast=True)
                message_found = True
            else:
                # Можна надіслати помилку користувачу, якщо він намагається видалити чуже повідомлення
                emit('action_error', {'message': 'Ви не можете видалити це повідомлення.'}, room=user_sid)
            break
    # Якщо повідомлення не знайдено (можливо, вже видалено або невірний ID)
    if not message_found and requesting_user:
        emit('action_error', {'message': 'Повідомлення для видалення не знайдено.'}, room=user_sid)

@socketio.on('edit_message')
def handle_edit_message(data):
    message_id_to_edit = data.get('messageId')
    new_text = data.get('newText')
    user_sid = request.sid
    requesting_user = users.get(user_sid)

    for message in history:
        if message.get('messageId') == message_id_to_edit and message.get('user') == requesting_user and message.get('type') == 'text':
            message['text'] = new_text
            # Надсилаємо оновлене повідомлення всім. Важливо передати 'user', щоб фронтенд знав, хто автор.
            emit('message_edited', {'messageId': message_id_to_edit, 'newText': new_text, 'user': requesting_user}, broadcast=True)
            return
    # Якщо повідомлення не знайдено або не може бути відредаговано
    if requesting_user:
        emit('action_error', {'message': 'Повідомлення для редагування не знайдено або не може бути змінено.'}, room=user_sid)

@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
