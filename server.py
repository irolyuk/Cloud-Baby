from flask import Flask, request # type: ignore
from flask_socketio import SocketIO, send, emit # type: ignore
from flask_cors import CORS # type: ignore
import uuid # Для генерації унікальних ID
import threading
import time # Потрібен для відстеження часу

app = Flask(__name__)
CORS(app) # Дозволяє запити з усіх джерел

# Ініціалізація SocketIO зі збільшеними таймаутами для стабільності
socketio = SocketIO(app,
cors_allowed_origins="*",
max_http_buffer_size=10 * 1024 * 1024, # Збільшуємо до 10MB
ping_timeout=60,    # Час очікування відповіді pong (в секундах)
ping_interval=25)   # Інтервал надсилання ping (в секундах)

users = {}  # Зберігає нікнейми активних користувачів
history = []
current_global_track = None # Зберігає поточний глобальний трек: {'audiosrc': 'path/to/song.mp3'} або None


@socketio.on('connect')
def handle_connect():
    # При підключенні нового клієнта, надсилаємо йому поточний стан музики
    global current_global_track
    if current_global_track:
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': current_global_track['audiosrc']}, to=request.sid)
    else:
        emit('update_global_music_state', {'status': 'stopped'}, to=request.sid)
    
    # Решта логіки підключення (наприклад, очікування 'register') залишається
@socketio.on('register')
def handle_register(nickname):
    global current_global_track # Доступ до глобальних змінних
    users[request.sid] = nickname
    emit("users_online", list(users.values()), broadcast=True)
    # Також надсилаємо стан музики після реєстрації, якщо connect спрацював раніше
    # (це для надійності, хоча emit в 'connect' має спрацювати)
    if current_global_track:
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': current_global_track['audiosrc']}, to=request.sid)
    else:
        emit('update_global_music_state', {'status': 'stopped'}, to=request.sid)
    
    # Логіка запуску таймера Тамагочі видалена


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
        "image": msg.get('image'),       # Дані зображення, будуть None для тексту
        "replyTo": msg.get('replyTo')    # Додаємо інформацію про відповідь
    }
    
    history.append(message_data)
    if len(history) > 50:
        history.pop(0)
    socketio.emit('message', message_data) # Надсилаємо всім, включаючи відправника

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

    # global history # 'global' не потрібен тут, оскільки ми модифікуємо список на місці
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
                emit('action_error', {'message': 'Ви не можете видалити це повідомлення.'}, to=user_sid)
            break
    # Якщо повідомлення не знайдено (можливо, вже видалено або невірний ID)
    if not message_found and requesting_user: # Переконуємося, що requesting_user існує перед надсиланням помилки
        emit('action_error', {'message': 'Повідомлення для видалення не знайдено.'}, to=user_sid)

@socketio.on('edit_message')
def handle_edit_message(data):
    message_id_to_edit = data.get('messageId')
    new_text = data.get('newText')
    user_sid = request.sid
    requesting_user = users.get(user_sid)

    if not requesting_user: # Користувач міг відключитися
        return

    for message in history:
        if message.get('messageId') == message_id_to_edit and message.get('user') == requesting_user and message.get('type') == 'text':
            message['text'] = new_text
            # Надсилаємо оновлене повідомлення всім. Важливо передати 'user', щоб фронтенд знав, хто автор.
            emit('message_edited', {'messageId': message_id_to_edit, 'newText': new_text, 'user': requesting_user}, broadcast=True)
            return
    # Якщо повідомлення не знайдено або не може бути відредаговано
    emit('action_error', {'message': 'Повідомлення для редагування не знайдено або не може бути змінено.'}, to=user_sid)

@socketio.on('control_global_music')
def handle_control_global_music(data):
    global current_global_track
    action = data.get('action')
    audiosrc = data.get('audiosrc') # audiosrc потрібен для 'play' та 'stop_after_ended'

    if action == 'play' and audiosrc:
        current_global_track = {'audiosrc': audiosrc}
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': audiosrc}, broadcast=True)
    elif action == 'stop':
        current_global_track = None
        emit('update_global_music_state', {'status': 'stopped'}, broadcast=True)
    elif action == 'stop_after_ended' and audiosrc:
        # Зупиняємо, тільки якщо це дійсно поточний трек, який закінчився
        if current_global_track and current_global_track['audiosrc'] == audiosrc:
            current_global_track = None
            emit('update_global_music_state', {'status': 'stopped'}, broadcast=True)

# Можливо, знадобиться обробник для явного запиту стану музики,
# але логіка в 'connect' та 'register' має покривати більшість випадків.
# @socketio.on('get_current_music_state')
# def handle_get_current_music_state():
#     # ... логіка надсилання поточного стану, схожа на ту, що в 'connect' ...

@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
