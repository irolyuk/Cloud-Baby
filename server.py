from flask import Flask, request, Response # type: ignore
from flask_socketio import SocketIO, send, emit # type: ignore
from flask_cors import CORS # type: ignore
import uuid # Для генерації унікальних ID
import threading
import time # Потрібен для відстеження часу
from functools import wraps # Для створення декораторів
import os # Для доступу до змінних середовища
from werkzeug.middleware.proxy_fix import ProxyFix # Додаємо імпорт ProxyFix


app = Flask(__name__)
CORS(app) # Дозволяє запити з усіх джерел

# Ініціалізація SocketIO зі збільшеними таймаутами для стабільності
socketio = SocketIO(app,
cors_allowed_origins="*",
max_http_buffer_size=10 * 1024 * 1024, # Збільшуємо до 10MB
ping_timeout=60,    # Час очікування відповіді pong (в секундах)
ping_interval=25)   # Інтервал надсилання ping (в секундах)

# Застосовуємо ProxyFix, щоб правильно визначати IP клієнта за проксі (наприклад, на Render)
# x_for=1 означає, що ми довіряємо одному проксі-серверу попереду.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# --- Адміністративний пароль ---
# Краще встановити через змінну середовища ADMIN_PASSWORD
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin') # Можна також задати ім'я користувача
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')

if not ADMIN_PASSWORD:
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print("!!! УВАГА: Змінна середовища ADMIN_PASSWORD не встановлена!                 !!!")
    print("!!! Доступ до адмін-панелі (/admin/online_users) буде неможливим.         !!!")
    print("!!! Будь ласка, встановіть ADMIN_PASSWORD у налаштуваннях вашого середовища. !!!")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

# --- Пароль для входу в чат (клієнтська сторона) ---
CHAT_ENTRY_PASSWORD = os.environ.get('CHAT_ENTRY_PASSWORD')
if not CHAT_ENTRY_PASSWORD:
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    print("!!! УВАГА: Змінна середовища CHAT_ENTRY_PASSWORD не встановлена!            !!!")
    print("!!! Вхід у чат через пароль на клієнті може не працювати належним чином.   !!!")
    print("!!! Будь ласка, встановіть CHAT_ENTRY_PASSWORD.                             !!!")
    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

users = {}  # Зберігає нікнейми активних користувачів
history = []
current_global_track = None # Зберігає поточний глобальний трек: {'audiosrc': 'path/to/song.mp3'} або None
current_global_theme = 'default' # Зберігаємо поточну глобальну тему


@socketio.on('connect')
def handle_connect():
    # При підключенні нового клієнта, надсилаємо йому поточний стан музики
    global current_global_track, current_global_theme
    user_agent_string = request.headers.get('User-Agent', 'N/A')
    accept_language = request.headers.get('Accept-Language', 'N/A')
    print(f"Client connected from IP: {request.remote_addr}, SID: {request.sid}, User-Agent: {user_agent_string}, Lang: {accept_language}")
    if current_global_track:
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': current_global_track['audiosrc']}, to=request.sid)
    else:
        emit('update_global_music_state', {'status': 'stopped'}, to=request.sid)
    
    # Надсилаємо поточну глобальну тему новому клієнту
    emit('theme_changed_globally', {'theme': current_global_theme}, to=request.sid)
    
    # Решта логіки підключення (наприклад, очікування 'register') залишається
@socketio.on('register')
def handle_register(nickname):
    global current_global_track, current_global_theme # Доступ до глобальних змінних
    user_agent_string = request.headers.get('User-Agent', 'N/A')
    accept_language = request.headers.get('Accept-Language', 'N/A')
    users[request.sid] = {'nickname': nickname, 'ip': request.remote_addr, 'user_agent': user_agent_string, 'language': accept_language}
    print(f"User {nickname} (SID: {request.sid}, IP: {request.remote_addr}, User-Agent: {user_agent_string}, Lang: {accept_language}) registered.")
    emit("users_online", [data['nickname'] for data in users.values()], broadcast=True)
    # Також надсилаємо стан музики після реєстрації, якщо connect спрацював раніше
    # (це для надійності, хоча emit в 'connect' має спрацювати)
    if current_global_track:
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': current_global_track['audiosrc']}, to=request.sid)
    else:
        emit('update_global_music_state', {'status': 'stopped'}, to=request.sid)
    
    # Надсилаємо поточну глобальну тему після реєстрації
    emit('theme_changed_globally', {'theme': current_global_theme}, to=request.sid)
    
    # Логіка запуску таймера Тамагочі видалена


@socketio.on('message')
def handle_message(msg):
    # Тепер 'msg' - це об'єкт: { type: 'text'/'image', text: '...', image: '...' }
    user_sid = request.sid
    user_data = users.get(user_sid)
    user_nickname = user_data['nickname'] if user_data else "Unknown"

    # Створюємо об'єкт повідомлення для збереження та відправки
    message_data = {
        "messageId": str(uuid.uuid4()), # Генеруємо унікальний ID для повідомлення
        "user": user_nickname,
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
    user_data = users.get(request.sid)
    user_nickname = user_data['nickname'] if user_data else "Unknown"
    emit("typing", {"user": user_nickname, "typing": is_typing}, broadcast=True, include_self=False)

@socketio.on('delete_message')
def handle_delete_message(data):
    message_id_to_delete = data.get('messageId')
    user_sid = request.sid
    requesting_user_data = users.get(user_sid)
    requesting_user_nickname = requesting_user_data['nickname'] if requesting_user_data else None

    # global history # 'global' не потрібен тут, оскільки ми модифікуємо список на місці
    message_found = False
    for message in history:
        if message.get('messageId') == message_id_to_delete:
            # Перевірка, чи користувач, який видаляє, є автором повідомлення
            if message.get('user') == requesting_user_nickname:
                history.remove(message)
                emit('message_deleted', {'messageId': message_id_to_delete}, broadcast=True)
                message_found = True
            else:
                # Можна надіслати помилку користувачу, якщо він намагається видалити чуже повідомлення
                if requesting_user_nickname: # Надсилаємо помилку, тільки якщо користувач ще підключений
                    emit('action_error', {'message': 'Ви не можете видалити це повідомлення.'}, to=user_sid)
            break
    # Якщо повідомлення не знайдено (можливо, вже видалено або невірний ID)
    if not message_found and requesting_user_nickname: # Переконуємося, що requesting_user існує перед надсиланням помилки
        emit('action_error', {'message': 'Повідомлення для видалення не знайдено.'}, to=user_sid)

@socketio.on('edit_message')
def handle_edit_message(data):
    message_id_to_edit = data.get('messageId')
    new_text = data.get('newText')
    user_sid = request.sid
    requesting_user_data = users.get(user_sid)
    requesting_user_nickname = requesting_user_data['nickname'] if requesting_user_data else None

    if not requesting_user_nickname: # Користувач міг відключитися або не зареєстрований
        return

    for message in history:
        if message.get('messageId') == message_id_to_edit and message.get('user') == requesting_user_nickname and message.get('type') == 'text':
            message['text'] = new_text
            # Надсилаємо оновлене повідомлення всім. Важливо передати 'user', щоб фронтенд знав, хто автор.
            emit('message_edited', {'messageId': message_id_to_edit, 'newText': new_text, 'user': requesting_user_nickname}, broadcast=True)
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

@socketio.on('request_global_theme_change')
def handle_request_global_theme_change(data):
    global current_global_theme
    new_theme = data.get('theme')
    if new_theme in ['default', 'black-metal']: # Валідація
        user_data = users.get(request.sid)
        user_nickname = user_data['nickname'] if user_data else "Unknown"
        user_ip = user_data.get('ip', request.remote_addr) if user_data else request.remote_addr
        user_agent = user_data.get('user_agent', request.headers.get('User-Agent', 'N/A')) if user_data else request.headers.get('User-Agent', 'N/A') # TODO: Refactor this logic
        user_lang = user_data.get('language', request.headers.get('Accept-Language', 'N/A')) if user_data else request.headers.get('Accept-Language', 'N/A')
        current_global_theme = new_theme
        print(f"Global theme changed to: {current_global_theme} by {user_nickname} (IP: {user_ip}, SID: {request.sid}, User-Agent: {user_agent}, Lang: {user_lang})")
        emit('theme_changed_globally', {'theme': current_global_theme}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    user_sid = request.sid
    if user_sid in users:
        user_data = users.pop(user_sid)
        nickname = user_data['nickname']
        ip_address = user_data['ip']
        user_agent = user_data.get('user_agent', 'N/A') # Отримуємо user_agent, якщо він був збережений
        language = user_data.get('language', 'N/A')
        print(f"User {nickname} (SID: {user_sid}, IP: {ip_address}, User-Agent: {user_agent}, Lang: {language}) disconnected.")
        # Оновлюємо список онлайн користувачів для всіх інших
        emit("users_online", [data['nickname'] for data in users.values()], broadcast=True)
    else:
        user_agent_string = request.headers.get('User-Agent', 'N/A') # Намагаємося отримати User-Agent, якщо можливо
        accept_language = request.headers.get('Accept-Language', 'N/A')
        print(f"User with SID: {user_sid} (IP: {request.remote_addr}, User-Agent: {user_agent_string}, Lang: {accept_language}) disconnected before registration or was already removed.")


# Можливо, знадобиться обробник для явного запиту стану музики,
# але логіка в 'connect' та 'register' має покривати більшість випадків.
# @socketio.on('get_current_music_state')
# def handle_get_current_music_state():
#     # ... логіка надсилання поточного стану, схожа на ту, що в 'connect' ...


@app.route('/')
def index():
    return "WebSocket сервер працює!"

# --- Декоратор для HTTP Basic Auth ---
def check_auth(username, password):
    """Перевіряє, чи надані ім'я користувача та пароль є правильними."""
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def authenticate():
    """Надсилає відповідь 401 Unauthorized, запитуючи аутентифікацію."""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route('/admin/online_users')
@requires_auth # Застосовуємо декоратор аутентифікації
def show_online_users():
    online_users_details = []
    for sid, data in users.items():
        online_users_details.append({
            'sid': sid,
            'nickname': data['nickname'],
            'ip': data.get('ip', 'N/A'),
            'user_agent': data.get('user_agent', 'N/A'),
            'language': data.get('language', 'N/A') # Додаємо мову
        })
    return {"online_users_details": online_users_details, "count": len(users)}

@app.route('/api/chat-config')
def chat_config():
    # Повертаємо конфігурацію, включаючи пароль для входу, якщо він встановлений
    return {"entryPassword": CHAT_ENTRY_PASSWORD if CHAT_ENTRY_PASSWORD else ""}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)
