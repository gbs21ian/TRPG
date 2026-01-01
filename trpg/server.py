import os
import json
import hashlib
import random
import string
from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room, close_room

app = Flask(__name__)
# 보안상의 이유로 secret_key를 설정하는 것이 좋지만, 로컬 테스트용이므로 간단히 설정
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# 데이터 저장 경로
DATA_DIR = os.path.join(os.getcwd(), 'saves')
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- Room Management (In-Memory) ---
# 실제 서비스에서는 Redis 등을 사용해야 하지만, 여기서는 메모리 딕셔너리로 관리
# rooms = {
#   "ROOM_CODE": {
#       "host": "socket_id",
#       "players": [ { "sid": "socket_id", "name": "PlayerName", "is_ready": False, "character": {...} } ],
#       "state": "waiting" | "playing",
#       "turn_index": 0
#   }
# }
rooms = {}

def generate_room_code(length=6):
    """랜덤 방 코드 생성"""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choice(chars) for _ in range(length))
        if code not in rooms:
            return code

def get_account_file(api_key):
    """API Key를 해싱하여 고유한 파일명을 생성합니다."""
    hashed = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
    return os.path.join(DATA_DIR, f"{hashed}.json")

# --- HTTP Routes ---

@app.route('/')
def serve_index():
    return send_from_directory('.', 'trpg.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    api_key = data.get('apiKey')
    if not api_key:
        return jsonify({"error": "API Key is required"}), 400

    filepath = get_account_file(api_key)
    if not os.path.exists(filepath):
        return jsonify({"saves": [], "message": "New account created"})
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            saves = json.load(f)
        return jsonify({"saves": saves})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/save', methods=['POST'])
def save_game():
    data = request.json
    api_key = data.get('apiKey')
    save_data = data.get('saveData')
    
    if not api_key or not save_data:
        return jsonify({"error": "Invalid data"}), 400

    filepath = get_account_file(api_key)
    saves = []
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                saves = json.load(f)
        except:
            saves = []

    save_id = save_data.get('id')
    existing_index = next((i for i, s in enumerate(saves) if s.get('id') == save_id), -1)
    
    if existing_index >= 0:
        saves[existing_index] = save_data
    else:
        saves.append(save_data)
        
    saves.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(saves, f, ensure_ascii=False, indent=2)
        return jsonify({"success": True, "saves": saves})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete', methods=['POST'])
def delete_save():
    data = request.json
    api_key = data.get('apiKey')
    save_id = data.get('saveId')

    if not api_key or not save_id:
        return jsonify({"error": "Invalid data"}), 400

    filepath = get_account_file(api_key)
    if not os.path.exists(filepath):
        return jsonify({"error": "Account not found"}), 404

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            saves = json.load(f)
        
        saves = [s for s in saves if s.get('id') != save_id]
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(saves, f, ensure_ascii=False, indent=2)
            
        return jsonify({"success": True, "saves": saves})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- SocketIO Events ---

@socketio.on('create_room')
def handle_create_room(data):
    """방 생성 요청"""
    player_name = data.get('name', 'Unknown')
    room_code = generate_room_code()
    
    rooms[room_code] = {
        "host": request.sid,
        "players": [{
            "sid": request.sid,
            "name": player_name,
            "is_ready": True, # 방장은 항상 준비됨
            "character": None
        }],
        "state": "waiting",
        "turn_index": 0,
        "chat_html": ""
    }
    
    join_room(room_code)
    emit('room_created', {"code": room_code, "players": rooms[room_code]["players"]})
    print(f"Room created: {room_code} by {player_name}")

@socketio.on('join_room')
def handle_join_room(data):
    """방 참가 요청"""
    room_code = data.get('code', '').upper()
    player_name = data.get('name', 'Guest')
    
    if room_code not in rooms:
        emit('error', {"message": "존재하지 않는 방입니다."})
        return
    
    room = rooms[room_code]
    if room["state"] != "waiting":
        emit('error', {"message": "이미 게임이 시작된 방입니다."})
        return
        
    if len(room["players"]) >= 4:
        emit('error', {"message": "방이 꽉 찼습니다."})
        return

    # 중복 참가 방지 (같은 소켓 ID가 이미 있는지 확인)
    if any(p['sid'] == request.sid for p in room['players']):
        return

    # 복원된 슬롯과 이름 매칭
    matched = False
    for p in room["players"]:
        if p["sid"] is None and p["name"] == player_name:
            p["sid"] = request.sid
            matched = True
            break
    if not matched:
        room["players"].append({
            "sid": request.sid,
            "name": player_name,
            "is_ready": False,
            "character": None
        })
    
    join_room(room_code)
    # 방에 있는 모두에게 플레이어 목록 갱신 알림
    emit('player_joined', {"players": room["players"]}, to=room_code)
    # 새 참가자에게 채팅 히스토리 동기화
    emit('sync_history', {"chat_html": room.get("chat_html", "")}, to=request.sid)
    print(f"{player_name} joined room {room_code}")

@socketio.on('update_character')
def handle_update_character(data):
    """캐릭터 정보 업데이트 (대기실에서)"""
    room_code = data.get('code')
    character = data.get('character')
    
    if room_code in rooms:
        room = rooms[room_code]
        for p in room['players']:
            if p['sid'] == request.sid:
                p['character'] = character
                p['is_ready'] = True # 캐릭터를 제출하면 준비 완료로 간주
                break
        
        emit('player_updated', {"players": room['players']}, to=room_code)

@socketio.on('restore_room')
def handle_restore_room(data):
    """호스트가 저장된 멀티플레이 데이터를 방에 복원"""
    room_code = data.get('code')
    players = data.get('players', [])
    turn_index = data.get('turn_index', 0)
    chat_html = data.get('chat_html', "")
    start_playing = data.get('start_playing', False)
    if room_code in rooms:
        # 호스트 SID 반영 및 슬롯 구성
        restored_players = []
        for idx, p in enumerate(players):
            name = p.get('name') or f"플레이어{idx+1}"
            restored_players.append({
                "sid": request.sid if idx == 0 else None,
                "name": name,
                "is_ready": True,
                "character": p.get('character')
            })
        rooms[room_code]["players"] = restored_players
        rooms[room_code]["turn_index"] = turn_index
        rooms[room_code]["chat_html"] = chat_html or ""
        rooms[room_code]["state"] = "playing" if start_playing else "waiting"
        emit('player_updated', {"players": rooms[room_code]["players"]}, to=room_code)
        emit('sync_history', {"chat_html": rooms[room_code]["chat_html"]}, to=room_code)
        if start_playing:
            emit('game_started', {
                "players": rooms[room_code]["players"],
                "turn_index": rooms[room_code]["turn_index"]
            }, to=room_code)

@socketio.on('start_game')
def handle_start_game(data):
    """게임 시작 (방장만 가능)"""
    room_code = data.get('code')
    if room_code in rooms:
        room = rooms[room_code]
        if room['host'] == request.sid:
            # 모든 플레이어가 준비되었는지 확인 (옵션)
            if all(p.get('is_ready') for p in room['players']):
                room['state'] = 'playing'
                emit('game_started', {
                    "players": room['players'],
                    "turn_index": 0
                }, to=room_code)
            else:
                emit('error', {"message": "모든 플레이어가 캐릭터를 생성해야 합니다."})

@socketio.on('send_action')
def handle_send_action(data):
    """플레이어 행동 전송"""
    room_code = data.get('code')
    content = data.get('content')
    
    if room_code in rooms:
        # 메시지를 모든 플레이어에게 브로드캐스트
        emit('new_message', {
            "sender": data.get('sender', 'Unknown'),
            "content": content,
            "type": "user"
        }, to=room_code)

@socketio.on('gm_response')
def handle_gm_response(data):
    """방장의 AI(GM)가 생성한 응답을 모두에게 공유"""
    room_code = data.get('code')
    content = data.get('content')
    
    if room_code in rooms:
        emit('new_message', {
            "sender": "GM",
            "content": content,
            "type": "assistant"
        }, to=room_code)

@socketio.on('next_turn')
def handle_next_turn(data):
    """턴 넘기기"""
    room_code = data.get('code')
    if room_code in rooms:
        room = rooms[room_code]
        current_idx = room['turn_index']
        next_idx = (current_idx + 1) % len(room['players'])
        room['turn_index'] = next_idx
        
        emit('turn_changed', {"turn_index": next_idx}, to=room_code)

@socketio.on('disconnect')
def handle_disconnect():
    """연결 종료 처리"""
    for code, room in list(rooms.items()):
        # 플레이어 제거
        room['players'] = [p for p in room['players'] if p['sid'] != request.sid]
        
        if not room['players']:
            # 방에 아무도 없으면 방 삭제
            del rooms[code]
        else:
            # 방장이 나갔으면 방장 승계
            if room['host'] == request.sid:
                room['host'] = room['players'][0]['sid']
            
            emit('player_left', {"players": room['players']}, to=code)

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting TRPG SocketIO Server on http://0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=True, allow_unsafe_werkzeug=True)
