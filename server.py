from flask import Flask, request # type: ignore
from flask_socketio import SocketIO, send, emit # type: ignore
from flask_cors import CORS # type: ignore
import uuid # Для генерації унікальних ID
import threading
import time # Потрібен для відстеження часу

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10 * 1024 * 1024) # Збільшуємо до 10MB

users = {}  # Зберігає нікнейми активних користувачів
history = []
current_global_track = None # Зберігає поточний глобальний трек: {'audiosrc': 'path/to/song.mp3'} або None

# --- Тамагочі ---
tamagotchi_state = None
tamagotchi_timer = None
TICK_INTERVAL = 20 # Тимчасово кожні 20 секунд для тестування

DEFAULT_TAMAGOTCHI_STATE = {
    "name": "Хмаринка",
    "hunger": 50,   # 0 (дуже голодний) - 100 (ситий)
    "happiness": 50, # 0 (дуже сумний) - 100 (щасливий)
    "is_alive": True,
    "last_interaction_time": time.time() # Час останньої взаємодії або оновлення
}

@socketio.on('connect')
def handle_connect():
    # При підключенні нового клієнта, надсилаємо йому поточний стан музики
    global current_global_track
    if current_global_track:
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': current_global_track['audiosrc']}, to=request.sid)
    else:
        emit('update_global_music_state', {'status': 'stopped'}, to=request.sid)
    
    # Надсилаємо стан Тамагочі, якщо він існує
    if tamagotchi_state and tamagotchi_state["is_alive"]:
        emit('update_tamagotchi_state', tamagotchi_state, to=request.sid)
    # Решта логіки підключення (наприклад, очікування 'register') залишається

@socketio.on('register')
def handle_register(nickname):
    global current_global_track # Доступ до глобальної змінної
    users[request.sid] = nickname
    emit("users_online", list(users.values()), broadcast=True)
    # Також надсилаємо стан музики після реєстрації, якщо connect спрацював раніше
    # (це для надійності, хоча emit в 'connect' має спрацювати)
    if current_global_track:
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': current_global_track['audiosrc']}, to=request.sid)
    else:
        emit('update_global_music_state', {'status': 'stopped'}, to=request.sid)
    
    # Також надсилаємо стан Тамагочі після реєстрації
    if tamagotchi_state and tamagotchi_state["is_alive"]:
        emit('update_tamagotchi_state', tamagotchi_state, to=request.sid)
    
    # Якщо це перший користувач онлайн і Тамагочі живий, але таймер неактивний, запускаємо його
    if len(users) == 1 and tamagotchi_state and tamagotchi_state["is_alive"] and not tamagotchi_timer:
        tamagotchi_timer = threading.Timer(TICK_INTERVAL, update_tamagotchi_passively)
        tamagotchi_timer.start()
        print(f"[{time.strftime('%H:%M:%S')}] Tamagotchi timer STARTED from REGISTER because it's the first user and Tamagotchi is alive.")

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in users:
        del users[request.sid]
    emit("users_online", list(users.values()), broadcast=True)
    # Якщо користувачів не залишилося онлайн і таймер Тамагочі активний, зупиняємо його
    if not users and tamagotchi_timer:
        tamagotchi_timer.cancel()
        tamagotchi_timer = None
        print(f"[{time.strftime('%H:%M:%S')}] Tamagotchi timer PAUSED because no users are online.")


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

# --- Тамагочі Обробники ---
def update_tamagotchi_passively():
    global tamagotchi_state, tamagotchi_timer
    current_timestamp = time.strftime('%H:%M:%S')
    print(f"[{current_timestamp}] update_tamagotchi_passively CALLED.")

    if not tamagotchi_state or not tamagotchi_state["is_alive"]:
        print(f"[{current_timestamp}] Tamagotchi is not initialized or not alive. Stopping timer if active.")
        if tamagotchi_timer:
            tamagotchi_timer.cancel()
            tamagotchi_timer = None
        return
    
    if not users: # Якщо немає користувачів онлайн, не оновлюємо стан і зупиняємо таймер
        print(f"[{current_timestamp}] No users online. Stopping timer if active.")
        if tamagotchi_timer:
            tamagotchi_timer.cancel()
            tamagotchi_timer = None
        return

    print(f"[{current_timestamp}] Tamagotchi is alive and users are online. Proceeding to update stats.")
    print(f"[{current_timestamp}] Current state BEFORE update: {tamagotchi_state}")

    # Зменшуємо показники з часом, але не частіше ніж раз на TICK_INTERVAL
    tamagotchi_state["hunger"] = max(0, tamagotchi_state["hunger"] - 5) # Голодніє
    tamagotchi_state["happiness"] = max(0, tamagotchi_state["happiness"] - 3) # Сумнішає
    tamagotchi_state["last_interaction_time"] = time.time() # Оновлюємо час останнього оновлення

    print(f"[{current_timestamp}] Current state AFTER update: {tamagotchi_state}")

    if tamagotchi_state["hunger"] == 0 or tamagotchi_state["happiness"] == 0:
        tamagotchi_state["is_alive"] = False
        print(f"[{current_timestamp}] {tamagotchi_state['name']} is no longer alive due to low stats.")
        emit('update_tamagotchi_state', tamagotchi_state, broadcast=True)
        if tamagotchi_timer:
            tamagotchi_timer.cancel()
            tamagotchi_timer = None
        return
    
    emit('update_tamagotchi_state', tamagotchi_state, broadcast=True)
    print(f"[{current_timestamp}] Emitted update_tamagotchi_state.")
    
    # Перезапускаємо таймер
    tamagotchi_timer = threading.Timer(TICK_INTERVAL, update_tamagotchi_passively)
    tamagotchi_timer.start()
    print(f"[{current_timestamp}] Tamagotchi timer RESTARTED for next tick.")

@socketio.on('initialize_tamagotchi')
def handle_initialize_tamagotchi():
    global tamagotchi_state, tamagotchi_timer
    tamagotchi_state = DEFAULT_TAMAGOTCHI_STATE.copy()
    tamagotchi_state["last_interaction_time"] = time.time()
    emit('update_tamagotchi_state', tamagotchi_state, broadcast=True)
    print(f"[{time.strftime('%H:%M:%S')}] {tamagotchi_state['name']} has been initialized/revived. State: {tamagotchi_state}")
    
    # Запускаємо таймер, тільки якщо є користувачі онлайн
    if users:
        if tamagotchi_timer:
            tamagotchi_timer.cancel()
            print(f"[{time.strftime('%H:%M:%S')}] Previous Tamagotchi timer cancelled during initialization.")
        tamagotchi_timer = threading.Timer(TICK_INTERVAL, update_tamagotchi_passively)
        tamagotchi_timer.start()
        print(f"[{time.strftime('%H:%M:%S')}] Tamagotchi timer STARTED from initialize_tamagotchi as users are online.")
    else:
        print(f"[{time.strftime('%H:%M:%S')}] Tamagotchi timer NOT started from initialize_tamagotchi as NO users are online.")

@socketio.on('tamagotchi_action')
def handle_tamagotchi_action(data):
    global tamagotchi_state
    if not tamagotchi_state or not tamagotchi_state["is_alive"]:
        emit('action_error', {'message': f'{DEFAULT_TAMAGOTCHI_STATE["name"]} спить або ще не створений.'}, to=request.sid)
        return
    print(f"[{time.strftime('%H:%M:%S')}] Tamagotchi action received: {data}. Current state: {tamagotchi_state}")

    action = data.get('action')
    if action == 'feed':
        tamagotchi_state["hunger"] = min(100, tamagotchi_state["hunger"] + 25)
        tamagotchi_state["happiness"] = min(100, tamagotchi_state["happiness"] + 5) # Їжа робить трохи щасливішим
    elif action == 'play':
        tamagotchi_state["happiness"] = min(100, tamagotchi_state["happiness"] + 30)
        tamagotchi_state["hunger"] = max(0, tamagotchi_state["hunger"] - 10) # Граючись, трохи голодніє
    tamagotchi_state["last_interaction_time"] = time.time()
    emit('update_tamagotchi_state', tamagotchi_state, broadcast=True)
    print(f"[{time.strftime('%H:%M:%S')}] Tamagotchi state after action '{action}': {tamagotchi_state}. Emitted update.")

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
