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

# Глобальні змінні для гри КНП
active_rps_games = {} # Словник для зберігання активних ігор
# { "game_id": { "players": [sid1, sid2], "nicknames": {sid1: "nick1", sid2: "nick2"}, "moves": {sid1: None, sid2: None}, "score": {"nick1": 0, "nick2": 0}, "status": "pending_acceptance/playing" } }
pending_rps_invites = {} # Словник для зберігання очікуючих запрошень {invited_sid: {"inviter_sid": inviter_sid, "game_id": game_id, "inviter_nickname": inviter_nickname}}


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


@socketio.on('disconnect')
def handle_disconnect():
    user_sid = request.sid
    disconnected_user_nickname = users.pop(user_sid, None) # Видаляємо і отримуємо нік

    if disconnected_user_nickname: # Якщо користувач був зареєстрований
        emit("users_online", list(users.values()), broadcast=True)
        print(f"Користувач {disconnected_user_nickname} ({user_sid}) відключився.")

        # Перевірка ігор КНП
        game_to_terminate_id = None
        for game_id, game_data in list(active_rps_games.items()): # list() для безпечної ітерації при видаленні
            if user_sid in game_data["players"]:
                game_to_terminate_id = game_id
                opponent_sid = get_opponent_sid(game_data, user_sid)
                if opponent_sid and users.get(opponent_sid): # Якщо суперник ще онлайн
                    emit('rps_opponent_quit', {'quitter_nickname': disconnected_user_nickname}, to=opponent_sid)
                break
        if game_to_terminate_id:
            active_rps_games.pop(game_to_terminate_id, None)
            print(f"Гра КНП ({game_to_terminate_id}) завершена через відключення {disconnected_user_nickname}.")

        # Перевірка очікуючих запрошень КНП
        # Якщо відключився той, кого запрошували
        if user_sid in pending_rps_invites:
            invite_data = pending_rps_invites.pop(user_sid)
            inviter_sid = invite_data["inviter_sid"]
            if users.get(inviter_sid): # Якщо той, хто запрошував, ще онлайн
                emit('status_message', {'message': f'{disconnected_user_nickname} відключився(-лась) і не може прийняти запрошення.'}, to=inviter_sid)
            print(f"Запрошення КНП для {disconnected_user_nickname} скасовано через відключення.")
        
        # Якщо відключився той, хто запрошував
        invite_to_remove_for_inviter_key = None
        for invited_op_sid, invite_d in pending_rps_invites.items():
            if invite_d["inviter_sid"] == user_sid:
                invite_to_remove_for_inviter_key = invited_op_sid
                if users.get(invited_op_sid): # Якщо той, кого запрошували, ще онлайн
                    emit('status_message', {'message': f'{disconnected_user_nickname}, який(-а) запрошував(ла) вас на гру, відключився(-лась).'}, to=invited_op_sid)
                break
        if invite_to_remove_for_inviter_key:
            pending_rps_invites.pop(invite_to_remove_for_inviter_key, None)
            print(f"Запрошення КНП від {disconnected_user_nickname} скасовано через його/її відключення.")
    else:
        print(f"Користувач ({user_sid}) відключився (не був зареєстрований).")


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

    message_found = False
    for message in history:
        if message.get('messageId') == message_id_to_delete:
            if message.get('user') == requesting_user:
                history.remove(message)
                emit('message_deleted', {'messageId': message_id_to_delete}, broadcast=True)
                message_found = True
            else:
                emit('action_error', {'message': 'Ви не можете видалити це повідомлення.'}, to=user_sid)
            break
    if not message_found and requesting_user: 
        emit('action_error', {'message': 'Повідомлення для видалення не знайдено.'}, to=user_sid)

@socketio.on('edit_message')
def handle_edit_message(data):
    message_id_to_edit = data.get('messageId')
    new_text = data.get('newText')
    user_sid = request.sid
    requesting_user = users.get(user_sid)

    if not requesting_user: 
        return

    for message in history:
        if message.get('messageId') == message_id_to_edit and message.get('user') == requesting_user and message.get('type') == 'text':
            message['text'] = new_text
            emit('message_edited', {'messageId': message_id_to_edit, 'newText': new_text, 'user': requesting_user}, broadcast=True)
            return
    emit('action_error', {'message': 'Повідомлення для редагування не знайдено або не може бути змінено.'}, to=user_sid)

@socketio.on('control_global_music')
def handle_control_global_music(data):
    global current_global_track
    action = data.get('action')
    audiosrc = data.get('audiosrc') 

    if action == 'play' and audiosrc:
        current_global_track = {'audiosrc': audiosrc}
        emit('update_global_music_state', {'status': 'playing', 'audiosrc': audiosrc}, broadcast=True)
    elif action == 'stop':
        current_global_track = None
        emit('update_global_music_state', {'status': 'stopped'}, broadcast=True)
    elif action == 'stop_after_ended' and audiosrc:
        if current_global_track and current_global_track['audiosrc'] == audiosrc:
            current_global_track = None
            emit('update_global_music_state', {'status': 'stopped'}, broadcast=True)

# --- Обробники для гри Камінь, Ножиці, Папір ---

def get_opponent_sid(game_data, player_sid):
    """Допоміжна функція для отримання SID суперника в грі."""
    for p_sid in game_data["players"]:
        if p_sid != player_sid:
            return p_sid
    return None

@socketio.on('propose_rps_game')
def handle_propose_rps_game():
    proposer_sid = request.sid
    proposer_nickname = users.get(proposer_sid)

    if not proposer_nickname:
        emit('action_error', {'message': 'Помилка: ваш нікнейм не зареєстровано.'}, to=proposer_sid)
        return

    if len(users) < 2:
        emit('action_error', {'message': 'Для гри потрібно двоє гравців онлайн.'}, to=proposer_sid)
        return

    opponent_sid = None
    for sid_in_chat in users:
        if sid_in_chat != proposer_sid:
            opponent_sid = sid_in_chat
            break
    
    opponent_nickname = users.get(opponent_sid)

    if not opponent_sid or not opponent_nickname: 
        emit('action_error', {'message': 'Не вдалося знайти суперника для гри.'}, to=proposer_sid)
        return

    for game_id_check, game_data_check in active_rps_games.items():
        if proposer_sid in game_data_check["players"] and opponent_sid in game_data_check["players"]:
            emit('action_error', {'message': 'Ви вже граєте або маєте активне запрошення з цим гравцем.'}, to=proposer_sid)
            return
    
    if opponent_sid in pending_rps_invites or \
       any(invite['inviter_sid'] == proposer_sid for invite in pending_rps_invites.values()) or \
       any(invite['inviter_sid'] == opponent_sid for invite in pending_rps_invites.values()):
        emit('action_error', {'message': 'Один з гравців вже має активне запрошення.'}, to=proposer_sid)
        return

    game_id = str(uuid.uuid4())
    pending_rps_invites[opponent_sid] = {"inviter_sid": proposer_sid, "game_id": game_id, "inviter_nickname": proposer_nickname}
    
    print(f"Гра КНП: {proposer_nickname} ({proposer_sid}) запросив {opponent_nickname} ({opponent_sid}). Game ID: {game_id}")
    emit('rps_invitation', {'game_id': game_id, 'inviter_nickname': proposer_nickname}, to=opponent_sid)
    emit('status_message', {'message': f'Запрошення на гру надіслано до {opponent_nickname}.'}, to=proposer_sid)

@socketio.on('rps_accept_invite')
def handle_rps_accept_invite(data):
    accepter_sid = request.sid
    accepter_nickname = users.get(accepter_sid)
    game_id = data.get('game_id')

    if not accepter_nickname: return
    
    invite_data = pending_rps_invites.pop(accepter_sid, None) 

    if not invite_data or invite_data["game_id"] != game_id:
        emit('action_error', {'message': 'Запрошення не знайдено або застаріло.'}, to=accepter_sid)
        return

    inviter_sid = invite_data["inviter_sid"]
    inviter_nickname = users.get(inviter_sid) 

    if not inviter_nickname: 
        emit('action_error', {'message': 'Гравець, що запрошував, відключився.'}, to=accepter_sid)
        return

    active_rps_games[game_id] = {
        "players": [inviter_sid, accepter_sid],
        "nicknames": {inviter_sid: inviter_nickname, accepter_sid: accepter_nickname},
        "moves": {inviter_sid: None, accepter_sid: None},
        "score": {inviter_nickname: 0, accepter_nickname: 0}, 
        "status": "playing"
    }
    print(f"Гра КНП: {accepter_nickname} прийняв запрошення від {inviter_nickname}. Game ID: {game_id}")
    
    game_start_data = {
        'game_id': game_id,
        'players': [inviter_nickname, accepter_nickname] 
    }
    socketio.emit('rps_game_started', game_start_data, room=inviter_sid)
    socketio.emit('rps_game_started', game_start_data, room=accepter_sid)

@socketio.on('rps_decline_invite')
def handle_rps_decline_invite(data):
    decliner_sid = request.sid
    decliner_nickname = users.get(decliner_sid)
    game_id = data.get('game_id')

    if not decliner_nickname: return

    invite_data = pending_rps_invites.pop(decliner_sid, None)

    if not invite_data or invite_data["game_id"] != game_id:
        return

    inviter_sid = invite_data["inviter_sid"]
    if users.get(inviter_sid): 
        print(f"Гра КНП: {decliner_nickname} відхилив запрошення від {users.get(inviter_sid)}. Game ID: {game_id}")
        emit('rps_invite_declined', {'decliner_nickname': decliner_nickname}, to=inviter_sid)

@socketio.on('rps_make_move')
def handle_rps_make_move(data):
    player_sid = request.sid
    player_nickname = users.get(player_sid)
    game_id = data.get('game_id')
    move = data.get('move')

    if not player_nickname or not game_id or not move or move not in ['rock', 'paper', 'scissors']:
        emit('action_error', {'message': 'Некоректний хід або дані гри.'}, to=player_sid)
        return

    game = active_rps_games.get(game_id)
    if not game or player_sid not in game["players"] or game["status"] != "playing":
        emit('action_error', {'message': 'Гра не знайдена або ви не є її учасником.'}, to=player_sid)
        return

    if game["moves"][player_sid] is not None:
        emit('action_error', {'message': 'Ви вже зробили хід у цьому раунді.'}, to=player_sid)
        return

    game["moves"][player_sid] = move
    print(f"Гра КНП ({game_id}): {player_nickname} зробив хід {move}")

    opponent_sid = get_opponent_sid(game, player_sid)
    
    if opponent_sid and game["moves"][opponent_sid] is not None:
        p1_sid, p2_sid = game["players"][0], game["players"][1]
        p1_nick, p2_nick = game["nicknames"][p1_sid], game["nicknames"][p2_sid]
        p1_move, p2_move = game["moves"][p1_sid], game["moves"][p2_sid]

        winner_nick = None
        result_message = ""

        if p1_move == p2_move:
            result_message = "Нічия!"
        elif (p1_move == 'rock' and p2_move == 'scissors') or \
             (p1_move == 'scissors' and p2_move == 'paper') or \
             (p1_move == 'paper' and p2_move == 'rock'):
            winner_nick = p1_nick
            game["score"][p1_nick] += 1
        else:
            winner_nick = p2_nick
            game["score"][p2_nick] += 1
        
        if winner_nick:
            result_message = f"{winner_nick} перемагає в раунді!"
        
        print(f"Гра КНП ({game_id}): Раунд завершено. {result_message}. Рахунок: {p1_nick} {game['score'][p1_nick]} - {p2_nick} {game['score'][p2_nick]}")

        round_result_data = {
            'game_id': game_id,
            'moves': { p1_nick: p1_move, p2_nick: p2_move },
            'result_message': result_message,
            'score': game["score"] 
        }
        socketio.emit('rps_round_result', round_result_data, room=p1_sid)
        socketio.emit('rps_round_result', round_result_data, room=p2_sid)

        game["moves"][p1_sid], game["moves"][p2_sid] = None, None 
    else:
        emit('rps_waiting_for_opponent', to=player_sid)
        if opponent_sid and users.get(opponent_sid): 
             emit('status_message', {'message': f'{player_nickname} зробив(ла) хід. Тепер ваша черга!'}, to=opponent_sid)

@socketio.on('quit_rps_game')
def handle_quit_rps_game(data):
    player_sid = request.sid
    player_nickname = users.get(player_sid)
    game_id = data.get('game_id')

    if not player_nickname or not game_id: return

    game = active_rps_games.pop(game_id, None) 
    if game and player_sid in game["players"]:
        print(f"Гра КНП ({game_id}): {player_nickname} покинув гру.")
        opponent_sid = get_opponent_sid(game, player_sid)
        if opponent_sid and users.get(opponent_sid): 
            emit('rps_opponent_quit', {'quitter_nickname': player_nickname}, to=opponent_sid)
        emit('status_message', {'message': 'Ви покинули гру КНП.'}, to=player_sid)


@app.route('/')
def index():
    return "WebSocket сервер працює!"

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host="0.0.0.0", port=port)