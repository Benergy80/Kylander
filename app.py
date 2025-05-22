from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import random
import time
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kylander_is_the_best_keep_it_secret_CHANGE_THIS!')

# Configure SocketIO for production
socketio = SocketIO(app, 
                   async_mode='eventlet',
                   cors_allowed_origins="*",  # Allow all origins for production
                   logger=True, 
                   engineio_logger=True)

# --- Game Constants ---
GAME_WIDTH = 800; GAME_HEIGHT = 600; GROUND_LEVEL = GAME_HEIGHT - 50
PLAYER_SPEED = 10 
PLAYER_JUMP_VELOCITY = -15; GRAVITY = 1
PLAYER_ATTACK_RANGE = 85  # INCREASED: More generous attack range
PLAYER_SPRITE_HALF_WIDTH = 35 
ATTACK_DURATION = 45      # INCREASED: Longer attacks for better clash timing
ATTACK_COOLDOWN = 20 
CLASH_STUN_DURATION = 30  # INCREASED: Even longer stun for more dramatic effect
KNOCKBACK_DISTANCE = 60   # INCREASED: Very noticeable knockback
MAX_WINS = 5; SPECIAL_LEVEL_WINS = 3 
SLIDESHOW_DURATION_MS = 6000; VICTORY_SCREEN_DURATION_MS = 4000
CONTROLS_SCREEN_DURATION_MS = 4000; CHURCH_INTRO_DURATION_MS = 4000  # FIXED: Restored 4 second controls screen
QUICKENING_FLASHES = 6; QUICKENING_FLASH_DURATION_MS = 100
MAX_PLAYERS_PER_ROOM = 2

PARIS_BG_COUNT = 7; CHURCH_BG_COUNT = 3; VICTORY_BG_COUNT = 10; SLIDESHOW_COUNT = 12
CHARACTER_NAMES = ["The Potzer", "The Kylander", "Darichris"]
AI_SID_PLACEHOLDER = "AI_PLAYER_SID" 

# BALANCED: AI constants - reduced frequency for better gameplay
AI_SPEED_MULTIPLIER = 0.4  # Slower AI movement for better positioning
AI_PREFERRED_DISTANCE = 60  # AI stays closer for more clashes
AI_DISTANCE_BUFFER = 15     # Smaller buffer zone for tighter combat
AI_ATTACK_FREQUENCY = 0.25  # REDUCED: Less frequent attacks (was 0.45)
AI_JUMP_FREQUENCY = 0.12    # REDUCED: Less jumping to stay in range
AI_DUCK_FREQUENCY = 0.15    # REDUCED: Less ducking for more engagement
AI_ATTACK_COOLDOWN_BONUS = 15  # Shorter cooldown for more action

# GENEROUS: Clash detection for epic moments but not overwhelming
CLASH_DETECTION_RANGE = 135  # Generous clash range
VERTICAL_CLASH_TOLERANCE = 95  # Forgiving vertical alignment

game_sessions = {}; game_room_id = 'default_room' 

# Performance optimization variables
last_broadcast_time = 0
BROADCAST_INTERVAL = 1.0 / 60  # 60 FPS max

def get_default_player_state(player_id_num, character_name_choice=None):
    player_id_str = f"player{player_id_num}"
    valid_char_name = character_name_choice if character_name_choice in CHARACTER_NAMES else None
    return {
        'id': player_id_str, 'sid': None, 'name': player_id_str, 
        'character_name': valid_char_name, 'original_character_name': valid_char_name, 'display_character_name': valid_char_name,
        'x': 150 if player_id_num == 1 else GAME_WIDTH - 150, 'y': GROUND_LEVEL,
        'health': 100, 'score': 0, 'facing': 1 if player_id_num == 1 else -1,
        'current_animation': 'idle', 'animation_frame_server': 0, 
        'is_attacking': False, 'attack_timer': 0, 'is_ducking': False, 'is_jumping': False,
        'vertical_velocity': 0, 'cooldown_timer': 0, 'has_hit_this_attack': False,
        'is_ready_next_round': False, '_ai_last_duck_time': 0, '_ai_last_jump_time': 0,
        'miss_swing': False,  # Track missed swings for sound effects
        'knockback_timer': 0,  # Track knockback state
        'is_moving_this_frame': False  # FIXED: Track if player is actively moving
    }

def get_default_room_state():
    return {
        'id': game_room_id, 'players': {}, 'current_screen': 'TITLE', 'game_mode': None,
        'player1_char_name_chosen': None, 'player2_char_name_chosen': None,
        'p1_selection_complete': False, 'p2_selection_complete': False,
        'p1_waiting_for_p2': False,  # Track if P1 is waiting for P2 to connect
        'match_score_p1': 0, 'match_score_p2': 0,
        'current_background_key': 'paris', 'current_background_index': 0,
        'special_level_active': False, 'special_swap_target_player_id': None, 
        'round_winner_player_id': None, 'game_winner_player_id': None,
        'last_update_time': time.time(), 'state_timer_ms': 0, 
        'ai_opponent_active': False, 'quickening_effect_active': False,
        'dark_quickening_effect_active': False, 'final_sound_played': False, 
        'available_victory_sfx_indices': list(range(5)), 
        'used_victory_sfx_indices': [], 
        'available_victory_bgs_player': list(range(VICTORY_BG_COUNT)), 
        'used_special_bgs': [], 
        'sfx_event_for_client': None,
        'swordeffects_playing': False,  # Track sword effects sound
        'clash_flash_timer': 0,  # Track clash flash effect
        # Track original character for special level reversion
        'special_level_original_p1_char': None,
        'special_level_original_p2_char': None,
        'slideshow_music_started': False,  # Track slideshow music state
        # Enhanced game mode tracking
        'is_local_multiplayer': False,  # True for local 2P, False for online 2P
        'online_mode': False  # True for online multiplayer
    }
game_sessions[game_room_id] = get_default_room_state()

def get_player_by_id(room_state, target_player_id):
    if target_player_id == AI_SID_PLACEHOLDER and AI_SID_PLACEHOLDER in room_state['players']: 
        return room_state['players'][AI_SID_PLACEHOLDER]
    for p_state in room_state['players'].values():
        if p_state['id'] == target_player_id: 
            return p_state
    return None

def get_opponent_state(room_state, player_state_or_sid):
    player_id_to_match = None; current_sid = None
    if isinstance(player_state_or_sid, str): 
        current_sid = player_state_or_sid
        if current_sid in room_state['players']: 
            player_id_to_match = room_state['players'][current_sid]['id']
    elif isinstance(player_state_or_sid, dict): 
        player_id_to_match = player_state_or_sid.get('id'); current_sid = player_state_or_sid.get('sid')
    if player_id_to_match:
        for p_sid_iter, p_data in room_state['players'].items():
            if p_sid_iter != current_sid: 
                return p_data
    return None

def cleanup_room_state(room_state):
    """Clean up any accumulated state that might cause memory issues"""
    for player_sid, player_state in room_state['players'].items():
        if 'miss_swing' in player_state:
            player_state['miss_swing'] = False
        if '_temp_animation_data' in player_state:
            del player_state['_temp_animation_data']
        # Reset knockback and movement tracking
        player_state['knockback_timer'] = 0
        player_state['is_moving_this_frame'] = False
    room_state['sfx_event_for_client'] = None
    room_state['swordeffects_playing'] = False
    room_state['clash_flash_timer'] = 0  # Reset clash flash effect

def reset_player_for_round(player_state, room_state): 
    player_state['health'] = 100
    player_state['x'] = 150 if player_state['id'] == 'player1' else GAME_WIDTH - 150
    player_state['y'] = GROUND_LEVEL
    player_state.update({'is_attacking': False, 'attack_timer': 0, 'cooldown_timer': 0, 'is_jumping': False, 
                         'is_ducking': False, 'vertical_velocity': 0, 'current_animation': 'idle', 
                         'has_hit_this_attack': False, 'is_ready_next_round': False,
                         'facing': 1 if player_state['id'] == 'player1' else -1,
                         'miss_swing': False, 'knockback_timer': 0, 'is_moving_this_frame': False})  
    # Proper asset swapping for special level
    if room_state['special_level_active'] and player_state['id'] == room_state['special_swap_target_player_id']:
        player_state['character_name'] = "Darichris" 
        player_state['display_character_name'] = "Darichris"
    else: 
        player_state['character_name'] = player_state['original_character_name'] 
        player_state['display_character_name'] = player_state['original_character_name']

def initialize_round(room_state):
    print("🎯 initialize_round called!")
    try:
        cleanup_room_state(room_state)
        
        room_state.update({'round_winner_player_id': None, 'state_timer_ms': 0, 
                           'quickening_effect_active': False, 'dark_quickening_effect_active': False,
                           'sfx_event_for_client': None, 'swordeffects_playing': False})
        
        print(f"🎯 Resetting {len(room_state['players'])} players")
        for p_state in room_state['players'].values(): 
            reset_player_for_round(p_state, room_state)
        
        if room_state['special_level_active']:
            print("🎯 Special level background")
            available_church_bgs = [i for i in range(CHURCH_BG_COUNT) if i not in room_state.get('used_special_bgs', [])]
            if not available_church_bgs: 
                room_state['used_special_bgs'] = []
                available_church_bgs = list(range(CHURCH_BG_COUNT))
            chosen_church_idx = random.choice(available_church_bgs)
            room_state.update({'current_background_key': 'church', 'current_background_index': chosen_church_idx})
            room_state.setdefault('used_special_bgs', []).append(chosen_church_idx)
        else:
            old_bg_index = room_state.get('current_background_index', -1)
            new_bg_index = (old_bg_index + 1) % PARIS_BG_COUNT
            room_state.update({'current_background_key': 'paris', 'current_background_index': new_bg_index})
        
        room_state['current_screen'] = 'PLAYING'
        print(f"🎯 ✅ Round initialized! Screen: {room_state['current_screen']}")
        
    except Exception as e:
        print(f"❌ EXCEPTION in initialize_round: {e}")
        import traceback
        traceback.print_exc()

def handle_round_victory(room_state, victor_player_id, loser_player_id):
    if room_state['current_screen'] not in ['PLAYING', 'SPECIAL']: 
        return
    
    cleanup_room_state(room_state)
    print(f"🏆 Round over! Winner: {victor_player_id}")
    
    if victor_player_id == 'player1': 
        room_state['match_score_p1'] += 1
    elif victor_player_id == 'player2': 
        room_state['match_score_p2'] += 1

    # Check for game winner IMMEDIATELY after score update
    if room_state['match_score_p1'] >= MAX_WINS or room_state['match_score_p2'] >= MAX_WINS:
        room_state['game_winner_player_id'] = victor_player_id
        print(f"🎉 MATCH WINNER determined: {victor_player_id}")
    
    room_state.update({'round_winner_player_id': victor_player_id, 'quickening_effect_active': True, 
                       'state_timer_ms': (QUICKENING_FLASHES * 2 * QUICKENING_FLASH_DURATION_MS) + 500,
                       'current_screen': room_state['current_screen']}) 

def handle_special_level_loss_by_swapped(room_state, original_victor_id): 
    print(f"⚔️ Player {original_victor_id} (original character) defeated Darichris (swapped character) in special level!")
    room_state.update({'dark_quickening_effect_active': True, 'game_winner_player_id': original_victor_id,
                       'state_timer_ms': (QUICKENING_FLASHES * 2 * QUICKENING_FLASH_DURATION_MS) + 500,
                       'current_screen': 'SPECIAL_END'})

def end_special_level(room_state):
    """Properly end special level and revert characters"""
    print("🏰 Ending special level, reverting characters")
    room_state['special_level_active'] = False
    room_state['special_swap_target_player_id'] = None
    
    # Revert characters to their original forms
    for player_sid, player_state in room_state['players'].items():
        if player_state['id'] == 'player1':
            orig_char = room_state.get('special_level_original_p1_char') or player_state['original_character_name']
            player_state['character_name'] = orig_char
            player_state['display_character_name'] = orig_char
        elif player_state['id'] == 'player2':
            orig_char = room_state.get('special_level_original_p2_char') or player_state['original_character_name']
            player_state['character_name'] = orig_char
            player_state['display_character_name'] = orig_char
    
    # Clear special level character tracking
    room_state['special_level_original_p1_char'] = None
    room_state['special_level_original_p2_char'] = None

def update_player_physics_and_timers(player_state):
    """FIXED: Better animation handling that preserves walk animations"""
    # Handle knockback - disable ALL movement during knockback
    if player_state.get('knockback_timer', 0) > 0:
        player_state['knockback_timer'] -= 1
        # Prevent all input processing during knockback
        player_state['is_attacking'] = False
        player_state['is_ducking'] = False
        player_state['is_moving_this_frame'] = False
        # Allow gravity for vertical knockback effect
        if player_state['is_jumping']:
            player_state['y'] += player_state['vertical_velocity']
            player_state['vertical_velocity'] += GRAVITY
            if player_state['y'] >= GROUND_LEVEL:
                player_state.update({'y': GROUND_LEVEL, 'is_jumping': False, 'vertical_velocity': 0})
                # Reset to idle when landing during knockback
                player_state['current_animation'] = 'idle'
        return  # Don't process any other movement during knockback
    
    # Handle jumping physics
    if player_state['is_jumping']:
        player_state['y'] += player_state['vertical_velocity']
        player_state['vertical_velocity'] += GRAVITY
        if player_state['y'] >= GROUND_LEVEL:
            player_state.update({'y': GROUND_LEVEL, 'is_jumping': False, 'vertical_velocity': 0})
            # FIXED: Only reset animation on landing if not doing other actions
            if not player_state['is_attacking'] and not player_state['is_ducking']: 
                # Check if we're still moving
                if player_state.get('is_moving_this_frame', False):
                    player_state['current_animation'] = 'walk'
                else:
                    player_state['current_animation'] = 'idle'
    
    # Handle cooldown timer
    if player_state['cooldown_timer'] > 0: 
        player_state['cooldown_timer'] -= 1
    
    # Handle attack duration and completion
    if player_state['is_attacking']:
        player_state['attack_timer'] -= 1
        if player_state['attack_timer'] <= 0:
            # Check for missed attacks to trigger sound
            if not player_state['has_hit_this_attack']:
                player_state['miss_swing'] = True
            player_state.update({
                'is_attacking': False, 
                'has_hit_this_attack': False, 
                'cooldown_timer': ATTACK_COOLDOWN
            })
            # FIXED: Proper animation reset after attacking
            if player_state['is_jumping']:
                player_state['current_animation'] = 'jump'
            elif player_state['is_ducking']:
                player_state['current_animation'] = 'duck'
            elif player_state.get('is_moving_this_frame', False):
                player_state['current_animation'] = 'walk'
            else:
                player_state['current_animation'] = 'idle'
    
    # FIXED: Only reset walk animation if we're NOT moving this frame
    if (not player_state['is_attacking'] and 
        not player_state['is_jumping'] and 
        not player_state['is_ducking'] and 
        player_state['current_animation'] == 'walk' and
        not player_state.get('is_moving_this_frame', False)):
        player_state['current_animation'] = 'idle'
    
    # Reset movement flag for next frame
    player_state['is_moving_this_frame'] = False

def apply_screen_wrap(player_state):
    """Handle screen wrapping for players"""
    if player_state['x'] > GAME_WIDTH + PLAYER_SPRITE_HALF_WIDTH: 
        player_state['x'] = -PLAYER_SPRITE_HALF_WIDTH + 1 
    elif player_state['x'] < -PLAYER_SPRITE_HALF_WIDTH: 
        player_state['x'] = GAME_WIDTH + PLAYER_SPRITE_HALF_WIDTH - 1

def update_ai(ai_state, target_state, room_state):
    """BALANCED: AI behavior optimized for good clashes without being overwhelming"""
    if not ai_state or not target_state or ai_state['health'] <= 0: 
        return
    
    update_player_physics_and_timers(ai_state)
    
    # Skip AI updates during knockback
    if ai_state['knockback_timer'] > 0:
        return
    
    # Calculate distance and direction
    dx = target_state['x'] - ai_state['x']
    distance = abs(dx)
    current_time_s = time.time()
    
    # Counter-attack behavior - more responsive but not overwhelming
    player_attacking = target_state.get('is_attacking', False)
    
    # Strategic ducking - only when really threatened
    if (target_state['is_attacking'] and distance < PLAYER_ATTACK_RANGE + 40 and 
        not ai_state['is_jumping'] and not player_attacking and  # Don't duck if we want to clash
        random.random() < AI_DUCK_FREQUENCY):
        if current_time_s - ai_state.get('_ai_last_duck_time', 0) > 3.0:
            ai_state.update({'is_ducking': True, 'current_animation': 'duck'})
            ai_state['_ai_last_duck_time'] = current_time_s
            print(f"🛡️ AI ducking defensively at distance {distance}")
    elif ai_state['is_ducking']:
        ai_state['is_ducking'] = False
        if not ai_state['is_attacking'] and not ai_state['is_jumping']:
            ai_state['current_animation'] = 'idle'
    
    # BALANCED: Attack logic with moderate counter-attack preference
    attack_frequency = AI_ATTACK_FREQUENCY
    
    # MODERATE boost when player is attacking (for clashes but not overwhelming)
    if player_attacking and distance <= CLASH_DETECTION_RANGE:
        attack_frequency = 0.65  # 65% chance to attack when player attacks nearby (was 90%)
        print(f"⚔️ AI counter-attack mode! Player attacking at distance {distance}")
    
    # Special level Darichris is more aggressive but reasonable
    if room_state.get('special_level_active') and ai_state.get('display_character_name') == 'Darichris':
        attack_frequency = min(0.75, attack_frequency * 1.2)  # 20% boost, max 75%
        print(f"👹 Darichris enhanced aggression! Attack frequency: {attack_frequency}")
    
    # Attack when in proper range
    if (not ai_state['is_attacking'] and ai_state['cooldown_timer'] == 0 and 
        not ai_state['is_ducking'] and 
        distance >= AI_PREFERRED_DISTANCE - AI_DISTANCE_BUFFER and
        distance <= PLAYER_ATTACK_RANGE + 25):  # More generous range
        
        if random.random() < attack_frequency:
            ai_state.update({
                'is_attacking': True, 
                'attack_timer': ATTACK_DURATION,
                'current_animation': 'jump_attack' if ai_state['is_jumping'] else 'attack',
                'has_hit_this_attack': False,
                'cooldown_timer': ATTACK_COOLDOWN + AI_ATTACK_COOLDOWN_BONUS
            })
            if player_attacking:
                print(f"🔥 AI counter-attacking! Both players attacking!")
    
    # Movement logic that prioritizes staying in clash range
    if not ai_state['is_attacking'] and not ai_state['is_ducking']:
        # Move less frequently when player is attacking (to stay in range for clashes)
        movement_chance = 0.4 if player_attacking else 0.7
        
        if random.random() >= (1 - movement_chance):
            target_distance = AI_PREFERRED_DISTANCE
            
            # If player is attacking, try to get into clash range
            if player_attacking:
                target_distance = min(AI_PREFERRED_DISTANCE, distance * 0.85)  # Get closer for clash
            
            if distance > target_distance + AI_DISTANCE_BUFFER:
                # Move closer
                move_speed = int(PLAYER_SPEED * AI_SPEED_MULTIPLIER)
                if dx > 0:
                    ai_state['x'] += move_speed
                    ai_state['facing'] = 1
                else:
                    ai_state['x'] -= move_speed
                    ai_state['facing'] = -1
                if not ai_state['is_jumping']:
                    ai_state['current_animation'] = 'walk'
                    ai_state['is_moving_this_frame'] = True  # FIXED: Track AI movement
            elif distance < target_distance - AI_DISTANCE_BUFFER:
                # Move away but slower when player attacking
                move_speed = int(PLAYER_SPEED * AI_SPEED_MULTIPLIER)
                if player_attacking:
                    move_speed = max(1, move_speed // 3)  # Much slower retreat during player attacks
                
                if dx > 0:
                    ai_state['x'] -= move_speed
                    ai_state['facing'] = 1
                else:
                    ai_state['x'] += move_speed
                    ai_state['facing'] = -1
                if not ai_state['is_jumping']:
                    ai_state['current_animation'] = 'walk'
                    ai_state['is_moving_this_frame'] = True  # FIXED: Track AI movement
            else:
                # In optimal range - stay put and face opponent
                if not ai_state['is_jumping']:
                    ai_state['current_animation'] = 'idle'
                ai_state['facing'] = 1 if dx > 0 else -1
        else:
            # Not moving - make sure animation is correct
            if not ai_state['is_jumping'] and not ai_state['is_attacking']:
                ai_state['current_animation'] = 'idle'
            ai_state['facing'] = 1 if dx > 0 else -1
    
    # Less frequent jumping to stay in fighting range
    if (not ai_state['is_jumping'] and not ai_state['is_ducking'] and 
        not player_attacking and  # Don't jump during potential clashes
        random.random() < AI_JUMP_FREQUENCY):
        if current_time_s - ai_state.get('_ai_last_jump_time', 0) > 5.0:
            ai_state.update({
                'is_jumping': True,
                'vertical_velocity': PLAYER_JUMP_VELOCITY,
                'current_animation': 'jump'
            })
            ai_state['_ai_last_jump_time'] = current_time_s
    
    apply_screen_wrap(ai_state)

def game_tick(room_state):
    """Main game logic loop with enhanced clash detection"""
    try:
        current_screen = room_state.get('current_screen', 'UNKNOWN')
        timer_val = room_state.get('state_timer_ms', 0)
        
        # Only log timer changes, not every tick
        if timer_val > 0 and timer_val % 500 < 17:  # Log roughly every 500ms
            print(f"⏰ Timer countdown: {timer_val:.0f}ms (screen: {current_screen})")
        
        current_time_s = time.time()
        delta_s = current_time_s - room_state['last_update_time']
        room_state['last_update_time'] = current_time_s
        
        # Limit delta time to prevent large jumps
        delta_s = min(delta_s, 1.0 / 30)
        
        # Clear previous frame's SFX events
        room_state['sfx_event_for_client'] = None 
        
        # Handle clash flash effect
        if room_state.get('clash_flash_timer', 0) > 0:
            room_state['clash_flash_timer'] -= 1

        # Timer handling logic (preserved from original)
        if room_state['state_timer_ms'] > 0:
            old_timer = room_state['state_timer_ms']
            room_state['state_timer_ms'] -= delta_s * 1000
            
            if room_state['state_timer_ms'] <= 0:
                prev_screen_when_timer_expired = room_state['current_screen'] 
                print(f"🚨 TIMER EXPIRED! Screen: {prev_screen_when_timer_expired}")
                
                if room_state['quickening_effect_active'] or room_state['dark_quickening_effect_active']:
                    room_state['quickening_effect_active'] = False
                    room_state['dark_quickening_effect_active'] = False
                    
                    if prev_screen_when_timer_expired == 'SPECIAL_END':
                        room_state.update({'current_screen': 'GAME_OVER', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                    elif room_state['game_winner_player_id']:
                        if prev_screen_when_timer_expired == 'SPECIAL_END':
                            room_state.update({'current_screen': 'GAME_OVER', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                        else:
                            room_state.update({'current_screen': 'FINAL', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS}) 
                        if not room_state['final_sound_played']: 
                            room_state['final_sound_played'] = True 
                    elif prev_screen_when_timer_expired == 'SPECIAL' and \
                         room_state['round_winner_player_id'] == room_state['special_swap_target_player_id']:
                        print("🏰 Darichris won special round. Showing church victory screen.")
                        room_state.update({'current_screen': 'CHURCH_VICTORY', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                        room_state['current_background_index'] = random.choice([0, 1])
                        end_special_level(room_state)
                    elif prev_screen_when_timer_expired == 'SPECIAL' and \
                         room_state['round_winner_player_id'] != room_state['special_swap_target_player_id']:
                        print("⚔️ Original character won special round. Showing normal church victory.")
                        room_state.update({'current_screen': 'CHURCH_VICTORY', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                        room_state['current_background_index'] = 0
                        end_special_level(room_state)
                    elif not room_state['special_level_active'] and \
                         (room_state['match_score_p1'] == SPECIAL_LEVEL_WINS or room_state['match_score_p2'] == SPECIAL_LEVEL_WINS) and \
                         room_state['round_winner_player_id']: 
                         room_state['special_level_active'] = True 
                         winner_of_trigger_round = room_state['round_winner_player_id']
                         p1 = get_player_by_id(room_state, 'player1')
                         p2 = get_player_by_id(room_state, 'player2')
                         if p1: 
                             room_state['special_level_original_p1_char'] = p1['original_character_name']
                         if p2: 
                             room_state['special_level_original_p2_char'] = p2['original_character_name']
                         
                         if room_state['match_score_p1'] == SPECIAL_LEVEL_WINS:
                             room_state['special_swap_target_player_id'] = 'player2'
                             print(f"🏆 Player 1 won 3 rounds. AI opponent (player2) becomes Darichris.")
                         else:
                             room_state['special_swap_target_player_id'] = 'player1'
                             print(f"🤖 AI opponent (player2) won 3 rounds. Player 1 becomes Darichris.")
                         
                         room_state.update({'current_screen': 'CHURCH_INTRO', 'state_timer_ms': CHURCH_INTRO_DURATION_MS})
                         print(f"🏰 Special Level triggered. Winner: {winner_of_trigger_round}. {room_state['special_swap_target_player_id']} becomes Darichris.")
                    else: 
                        room_state.update({'current_screen': 'VICTORY', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS, 'current_background_key': 'victory'})
                        if not room_state.get('available_victory_bgs_player'): 
                            room_state['available_victory_bgs_player'] = list(range(VICTORY_BG_COUNT))
                        if room_state['available_victory_bgs_player']:
                            idx = random.choice(room_state['available_victory_bgs_player'])
                            room_state['current_background_index'] = idx
                            room_state['available_victory_bgs_player'].remove(idx)
                        else: 
                            room_state['current_background_index'] = random.randint(0, VICTORY_BG_COUNT - 1)
                        
                        if not room_state.get('available_victory_sfx_indices'): 
                            room_state['available_victory_sfx_indices'] = list(range(5))
                        if room_state['available_victory_sfx_indices']:
                            sfx_idx = random.choice(room_state['available_victory_sfx_indices'])
                            room_state['victory_sfx_to_play_index'] = sfx_idx
                            room_state['available_victory_sfx_indices'].remove(sfx_idx)
                        else: 
                            room_state['victory_sfx_to_play_index'] = random.randint(0, 4)
                
                elif prev_screen_when_timer_expired == 'CONTROLS': 
                    print("🎯 CONTROLS timer expired - calling initialize_round!")
                    try:
                        initialize_round(room_state) 
                        print(f"✅ initialize_round completed! New screen: {room_state['current_screen']}")
                    except Exception as init_error:
                        print(f"❌ ERROR in initialize_round: {init_error}")
                        import traceback
                        traceback.print_exc()
                elif prev_screen_when_timer_expired == 'CHURCH_INTRO': 
                    print("🏰 Church intro expired - calling initialize_round!")
                    try:
                        initialize_round(room_state)
                        print(f"✅ Church intro initialize_round completed! New screen: {room_state['current_screen']}")
                    except Exception as init_error:
                        print(f"❌ ERROR in church intro initialize_round: {init_error}")
                        import traceback
                        traceback.print_exc() 
                elif prev_screen_when_timer_expired == 'CHURCH_VICTORY':
                    print("🏰 Church victory screen ended. Returning to normal gameplay.")
                    room_state['special_level_active'] = False
                    room_state['special_swap_target_player_id'] = None
                    room_state['special_level_original_p1_char'] = None
                    room_state['special_level_original_p2_char'] = None
                    initialize_round(room_state)
                elif prev_screen_when_timer_expired == 'CHURCH_VICTORY_IMMEDIATE':
                    print("🏰 Immediate church victory ended. Returning to normal gameplay.")
                    initialize_round(room_state)
                elif prev_screen_when_timer_expired == 'VICTORY':
                    if not room_state['game_winner_player_id']: 
                        initialize_round(room_state)
                elif prev_screen_when_timer_expired == 'FINAL': 
                    room_state.update({'current_screen': 'SLIDESHOW', 'current_background_key': 'slideshow', 
                                       'current_background_index': 0, 'state_timer_ms': SLIDESHOW_DURATION_MS,
                                       'slideshow_music_started': True})
                elif prev_screen_when_timer_expired == 'GAME_OVER':
                    room_state.update({'current_screen': 'SLIDESHOW', 'current_background_key': 'slideshow', 
                                       'current_background_index': 0, 'state_timer_ms': SLIDESHOW_DURATION_MS,
                                       'slideshow_music_started': True})

        # Slideshow management (preserved from original)
        if room_state['current_screen'] == 'SLIDESHOW':
            if room_state['state_timer_ms'] <= 0:
                if room_state['current_background_index'] >= SLIDESHOW_COUNT - 1:
                    print("📺 Slideshow completed naturally - returning to title")
                    room_state['slideshow_music_started'] = False
                    socketio.emit('update_room_state', room_state, room=game_room_id)
                    room_state['state_timer_ms'] = 200
                    room_state['current_screen'] = 'SLIDESHOW_TO_TITLE'
                else:
                    room_state['current_background_index'] = (room_state['current_background_index'] + 1) % SLIDESHOW_COUNT
                    room_state['state_timer_ms'] = SLIDESHOW_DURATION_MS
        
        elif room_state['current_screen'] == 'SLIDESHOW_TO_TITLE':
            if room_state['state_timer_ms'] <= 0:
                room_state.update({'current_screen': 'TITLE', 'current_background_key': 'paris',
                                   'current_background_index': 0, 'slideshow_music_started': False})
                room_state['match_score_p1'] = 0
                room_state['match_score_p2'] = 0
                room_state['final_sound_played'] = False

        # Main gameplay logic with generous clash detection
        if room_state['current_screen'] == 'PLAYING' or room_state['current_screen'] == 'SPECIAL':
            p1 = get_player_by_id(room_state, 'player1')
            p2 = get_player_by_id(room_state, 'player2')
            
            if p1: 
                update_player_physics_and_timers(p1)
            if p2:
                if room_state['ai_opponent_active']: 
                    update_ai(p2, p1, room_state)
                else: 
                    update_player_physics_and_timers(p2)
            
            # Handle miss swing sound effects
            if p1 and p1['miss_swing']:
                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'
                p1['miss_swing'] = False
            if p2 and p2['miss_swing']:
                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'
                p2['miss_swing'] = False
                
            if p1 and p2 and p1['health'] > 0 and p2['health'] > 0:
                p1_hit_this_tick = False
                p2_hit_this_tick = False
                
                # Enhanced collision detection with centered sprites
                SPRITE_CENTER_OFFSET_X = 0
                SPRITE_CENTER_OFFSET_Y = 25
                
                p1_center_x = p1['x'] + SPRITE_CENTER_OFFSET_X
                p1_center_y = p1['y'] - SPRITE_CENTER_OFFSET_Y
                p2_center_x = p2['x'] + SPRITE_CENTER_OFFSET_X
                p2_center_y = p2['y'] - SPRITE_CENTER_OFFSET_Y
                
                # GENEROUS: Clash detection with good forgiveness for epic clashes
                if p1['is_attacking'] and p2['is_attacking'] and \
                   p1['health'] > 0 and p2['health'] > 0 and \
                   abs(p1_center_x - p2_center_x) < CLASH_DETECTION_RANGE and \
                   abs(p1_center_y - p2_center_y) < VERTICAL_CLASH_TOLERANCE:
                    
                    # PREDICTIVE: Allow clash if attacks will overlap
                    p1_attack_active = p1['is_attacking'] and p1['attack_timer'] > 0
                    p2_attack_active = p2['is_attacking'] and p2['attack_timer'] > 0
                    
                    # GENEROUS: Allow clash with different attack timings
                    clash_time_window = ATTACK_DURATION * 0.15  # 15% through attack
                    p1_will_hit_soon = p1_attack_active and p1['attack_timer'] > clash_time_window
                    p2_will_hit_soon = p2_attack_active and p2['attack_timer'] > clash_time_window
                    
                    if (p1_will_hit_soon and p2_will_hit_soon and 
                        not p1['has_hit_this_attack'] and not p2['has_hit_this_attack']):
                        
                        print(f"💥 EPIC CLASH! P1 timer: {p1['attack_timer']}, P2 timer: {p2['attack_timer']}, Distance: {abs(p1_center_x - p2_center_x)}")
                        
                        # Dramatic clash effects
                        p1.update({
                            'has_hit_this_attack': True, 
                            'cooldown_timer': max(p1['cooldown_timer'], CLASH_STUN_DURATION), 
                            'attack_timer': min(p1['attack_timer'], 2)
                        })
                        p2.update({
                            'has_hit_this_attack': True, 
                            'cooldown_timer': max(p2['cooldown_timer'], CLASH_STUN_DURATION), 
                            'attack_timer': min(p2['attack_timer'], 2)
                        })
                        
                        # Massive knockback with enhanced effects
                        knockback_force = KNOCKBACK_DISTANCE + 25
                        if p1['x'] < p2['x']:
                            p1['x'] -= knockback_force
                            p2['x'] += knockback_force
                        else:
                            p1['x'] += knockback_force
                            p2['x'] -= knockback_force
                        
                        # Extended knockback duration for more drama
                        p1['knockback_timer'] = 40
                        p2['knockback_timer'] = 40
                        
                        # Dramatic vertical effects
                        if not p1['is_jumping']:
                            p1['vertical_velocity'] = -14
                            p1['is_jumping'] = True
                        if not p2['is_jumping']:
                            p2['vertical_velocity'] = -14
                            p2['is_jumping'] = True
                        
                        # Keep players on screen
                        p1['x'] = max(PLAYER_SPRITE_HALF_WIDTH, min(GAME_WIDTH - PLAYER_SPRITE_HALF_WIDTH, p1['x']))
                        p2['x'] = max(PLAYER_SPRITE_HALF_WIDTH, min(GAME_WIDTH - PLAYER_SPRITE_HALF_WIDTH, p2['x']))
                        
                        # Extended screen flash for drama
                        room_state['clash_flash_timer'] = 15
                        
                        print("🔥⚔️ LEGENDARY CLASH! ⚔️🔥")
                        room_state['sfx_event_for_client'] = 'sfx_swordClash'
                        
                else:
                    # No clash detected - check for individual hits
                    ATTACK_RANGE_EXTENSION = 55
                    HIT_BOX_WIDTH = 50
                    
                    if p1['is_attacking'] and not p1['has_hit_this_attack']:
                        if p1['facing'] == 1:
                            attack_x = p1_center_x + ATTACK_RANGE_EXTENSION
                        else:
                            attack_x = p1_center_x - ATTACK_RANGE_EXTENSION
                        
                        if abs(attack_x - p2_center_x) < HIT_BOX_WIDTH and \
                           abs(p1_center_y - p2_center_y) < VERTICAL_CLASH_TOLERANCE and \
                           not p2['is_ducking']:
                            p2['health'] -= 10
                            p1['has_hit_this_attack'] = True
                            p1_hit_this_tick = True
                            print(f"⚔️ P1 HIT P2. P2 Health: {p2['health']}")
                            room_state['sfx_event_for_client'] = 'sfx_swordSwing'
                            if p2['health'] <= 0:
                                if room_state['special_level_active']:
                                    if room_state['special_swap_target_player_id'] == 'player2' and p2.get('display_character_name') == "Darichris":
                                        print("💀 AI killed Darichris on holy ground! Dark quickening...")
                                        handle_special_level_loss_by_swapped(room_state, 'player1')
                                    else:
                                        print("🏆 Darichris defeated the AI! Church victory...")
                                        room_state.update({'current_screen': 'CHURCH_VICTORY_IMMEDIATE', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                                        room_state['current_background_index'] = random.choice([0, 1])
                                        room_state['round_winner_player_id'] = 'player2'  
                                        end_special_level(room_state)
                                else:
                                    handle_round_victory(room_state, 'player1', 'player2')
                    
                    if p2['is_attacking'] and not p2['has_hit_this_attack'] and p1['health'] > 0:
                        if p2['facing'] == 1:
                            attack_x = p2_center_x + ATTACK_RANGE_EXTENSION
                        else:
                            attack_x = p2_center_x - ATTACK_RANGE_EXTENSION
                        
                        if abs(attack_x - p1_center_x) < HIT_BOX_WIDTH and \
                           abs(p2_center_y - p1_center_y) < VERTICAL_CLASH_TOLERANCE and \
                           not p1['is_ducking']:
                            p1['health'] -= 10
                            p2['has_hit_this_attack'] = True
                            p2_hit_this_tick = True
                            print(f"⚔️ P2 HIT P1. P1 Health: {p1['health']}")
                            room_state['sfx_event_for_client'] = 'sfx_swordSwing'
                            if p1['health'] <= 0:
                                if room_state['special_level_active']:
                                    if room_state['special_swap_target_player_id'] == 'player1' and p1.get('display_character_name') == "Darichris":
                                        print("💀 AI killed Darichris on holy ground! Dark quickening...")
                                        handle_special_level_loss_by_swapped(room_state, 'player2')
                                    else:
                                        print("🏆 Darichris defeated the AI! Church victory...")
                                        room_state.update({'current_screen': 'CHURCH_VICTORY_IMMEDIATE', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                                        room_state['current_background_index'] = random.choice([0, 1])
                                        room_state['round_winner_player_id'] = 'player1'  
                                        end_special_level(room_state)
                                else:
                                    handle_round_victory(room_state, 'player2', 'player1')
                
                # Sword effects sound matching original
                if p1['is_attacking'] and p2['is_attacking'] and not room_state['swordeffects_playing']:
                    room_state['sfx_event_for_client'] = 'sfx_swordEffects'
                    room_state['swordeffects_playing'] = True
                elif not (p1['is_attacking'] and p2['is_attacking']):
                    room_state['swordeffects_playing'] = False
        
        # Always emit the room state update
        socketio.emit('update_room_state', room_state, room=game_room_id)
        
    except Exception as e:
        print(f"❌ EXCEPTION in game_tick: {e}")
        import traceback
        traceback.print_exc()

# Route handlers
@app.route('/')
def index(): 
    return render_template('index.html')

@app.route('/health')
def health_check():
    """Health check endpoint to verify server is running"""
    room = game_sessions.get(game_room_id)
    return {
        'status': 'ok',
        'room_exists': room is not None,
        'current_screen': room.get('current_screen', 'unknown') if room else 'no_room',
        'players_count': len(room.get('players', {})) if room else 0,
        'timestamp': time.time()
    }

# Socket event handlers
@socketio.on('connect')
def handle_connect():
    player_sid = request.sid
    room = game_sessions[game_room_id]
    print(f"🔌 Connect attempt: {player_sid}.")
    
    human_sids_in_room = [sid for sid in room['players'] if sid != AI_SID_PLACEHOLDER]
    assigned_player_id_str = None
    
    if not any(p['id'] == 'player1' for sid, p in room['players'].items() if sid != AI_SID_PLACEHOLDER): 
        assigned_player_id_str = "player1"
    elif not any(p['id'] == 'player2' for sid, p in room['players'].items() if sid != AI_SID_PLACEHOLDER) and len(human_sids_in_room) < MAX_PLAYERS_PER_ROOM:
        assigned_player_id_str = "player2"
    
    if assigned_player_id_str is None:
        print(f"🚫 Room full or slot error. SID {player_sid} rejected.")
        emit('room_full', room=player_sid)
        disconnect(player_sid)
        return
    
    player_id_num = 1 if assigned_player_id_str == "player1" else 2
    player_state = get_default_player_state(player_id_num)
    player_state['sid'] = player_sid
    
    if player_state['id'] == 'player1' and room['player1_char_name_chosen']: 
        player_state.update({'character_name': room['player1_char_name_chosen'], 
                            'original_character_name': room['player1_char_name_chosen'], 
                            'display_character_name': room['player1_char_name_chosen']})
    elif player_state['id'] == 'player2' and room['player2_char_name_chosen']: 
        player_state.update({'character_name': room['player2_char_name_chosen'], 
                            'original_character_name': room['player2_char_name_chosen'], 
                            'display_character_name': room['player2_char_name_chosen']})
    
    room['players'][player_sid] = player_state
    join_room(game_room_id)
    print(f"✅ Player {player_state['id']} ({player_sid}) connected. Total SIDs (inc AI): {len(room['players'])}.")
    
    # FIXED: Handle Player 2 connecting after Player 1 has already chosen
    if player_state['id'] == 'player2' and room['game_mode'] == 'TWO' and \
       room['p1_selection_complete'] and room['current_screen'] == 'CHARACTER_SELECT_P1':
        room['current_screen'] = 'CHARACTER_SELECT_P2'
        room['p1_waiting_for_p2'] = False
    elif player_state['id'] == 'player2' and room['game_mode'] in ['TWO', 'TWO_LOCAL', 'TWO_ONLINE'] and \
         room['p1_selection_complete'] and not room['p2_selection_complete'] and \
         room['current_screen'] != 'CHARACTER_SELECT_P2': 
        room['current_screen'] = 'CHARACTER_SELECT_P2'
    
    emit('assign_player_id', {'playerId': player_state['id'], 'initialRoomState': room}, room=player_sid)
    socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('disconnect')
def handle_disconnect():
    player_sid = request.sid
    room = game_sessions.get(game_room_id)
    
    if room and player_sid in room['players']:
        p_id_disc = room['players'][player_sid]['id']
        del room['players'][player_sid]
        print(f"❌ Player {p_id_disc} ({player_sid}) disconnected.")
        
        if p_id_disc == 'player1' and room['ai_opponent_active']:
            if AI_SID_PLACEHOLDER in room['players']: 
                del room['players'][AI_SID_PLACEHOLDER]
                print("🤖 AI player removed.")
            room['ai_opponent_active'] = False
        
        human_players_remaining_sids = [sid for sid in room['players'] if sid != AI_SID_PLACEHOLDER]
        
        if not human_players_remaining_sids: 
            game_sessions[game_room_id] = get_default_room_state()
            print("🔄 Room empty, resetting.")
        else: 
            print(f"👤 One player remains. Resetting room to TITLE.")
            room.update({'current_screen': 'TITLE', 'game_mode': None, 'ai_opponent_active': False,
                         'match_score_p1': 0, 'match_score_p2': 0, 'final_sound_played': False,
                         'player1_char_name_chosen': None, 'player2_char_name_chosen': None,
                         'p1_selection_complete': False, 'p2_selection_complete': False, 
                         'p1_waiting_for_p2': False,
                         'special_level_active': False,
                         'used_special_bgs': [], 'available_victory_sfx_indices': list(range(5))})
            
            rem_sid = human_players_remaining_sids[0]
            char_of_remaining = room['players'][rem_sid]['original_character_name'] if rem_sid in room['players'] and room['players'][rem_sid] else None
            new_p1_state = get_default_player_state(1, char_of_remaining)
            new_p1_state['sid'] = rem_sid
            
            if AI_SID_PLACEHOLDER in room['players']: 
                del room['players'][AI_SID_PLACEHOLDER]
            
            room['players'] = {rem_sid: new_p1_state}
            room['player1_char_name_chosen'] = char_of_remaining
            emit('assign_player_id', {'playerId': 'player1', 'initialRoomState': room}, room=rem_sid)
        
        socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('change_game_state')
def on_change_game_state(data):
    new_state = data.get('newState')
    room = game_sessions.get(game_room_id)
    player_sid = request.sid
    
    if not room or player_sid not in room['players']: 
        return
    
    print(f"🎮 P {room['players'][player_sid]['id']} req state {new_state} from {room['current_screen']}")
    
    if new_state == 'TITLE_SCREEN': 
        print("🏠 TITLE_SCREEN request - performing complete reset")
        room['slideshow_music_started'] = False
        room['current_screen'] = 'TITLE'
        
        socketio.emit('update_room_state', room, room=game_room_id)
        
        current_sids_map = {p['id']: sid for sid, p in room['players'].items() if sid != AI_SID_PLACEHOLDER}
        game_sessions[game_room_id] = get_default_room_state()
        new_room_state = game_sessions[game_room_id]
        
        if 'player1' in current_sids_map:
            p1_sid = current_sids_map['player1']
            p1_new = get_default_player_state(1)
            p1_new['sid'] = p1_sid
            new_room_state['players'][p1_sid] = p1_new
            emit('assign_player_id', {'playerId': 'player1', 'initialRoomState': new_room_state}, room=p1_sid)
        if 'player2' in current_sids_map:
            p2_sid = current_sids_map['player2']
            p2_new = get_default_player_state(2)
            p2_new['sid'] = p2_sid
            new_room_state['players'][p2_sid] = p2_new
            emit('assign_player_id', {'playerId': 'player2', 'initialRoomState': new_room_state}, room=p2_sid)
        
        if AI_SID_PLACEHOLDER in room['players']:
            del room['players'][AI_SID_PLACEHOLDER]
            room['ai_opponent_active'] = False
        
        room = new_room_state
        room['final_sound_played'] = False
        room['slideshow_music_started'] = False
    
    elif new_state == 'MODE_SELECT' and room['current_screen'] == 'TITLE': 
        room['current_screen'] = 'MODE_SELECT'
    elif new_state == 'CHARACTER_SELECT_P1' and room['current_screen'] == 'MODE_SELECT':
        mode = data.get('mode')
        # FIXED: Proper mode selection handling with complete state reset
        room.update({'game_mode': mode, 'current_screen': 'CHARACTER_SELECT_P1',
                     'p1_selection_complete': False, 'p2_selection_complete': False,
                     'player1_char_name_chosen': None, 'player2_char_name_chosen': None,
                     'p1_waiting_for_p2': False,  # Reset waiting flag
                     'ai_opponent_active': (mode == 'ONE')})
        
        for p_state_sid_iter in list(room['players'].keys()):
            player_obj = room['players'].get(p_state_sid_iter)
            if player_obj: 
                player_obj.update({'character_name': None, 'original_character_name': None, 'display_character_name': None})
    
    socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('player_character_choice')
def on_player_character_choice(data):
    char_name = data.get('characterName')
    player_sid = request.sid
    room = game_sessions.get(game_room_id)
    
    if not room or player_sid not in room['players'] or char_name not in CHARACTER_NAMES: 
        return

    player_data = room['players'][player_sid]
    print(f"👤 Player {player_data['id']} chose {char_name}")
    player_data.update({'character_name': char_name, 'original_character_name': char_name, 'display_character_name': char_name})

    ready_for_controls = False
    
    if room['current_screen'] == 'CHARACTER_SELECT_P1' and player_data['id'] == 'player1':
        room['player1_char_name_chosen'] = char_name
        room['p1_selection_complete'] = True
        
        if room['game_mode'] == 'ONE':
            room['ai_opponent_active'] = True
            # Select AI character (excluding player's choice and Darichris for normal gameplay)
            normal_ai_opponent_pool = [cn for cn in CHARACTER_NAMES if cn != char_name and cn != "Darichris"]
            if not normal_ai_opponent_pool:
                fallback_ai_pool = [cn for cn in CHARACTER_NAMES if cn != char_name]
                ai_char = random.choice(fallback_ai_pool) if fallback_ai_pool else CHARACTER_NAMES[0]
            else:
                ai_char = random.choice(normal_ai_opponent_pool)
            
            room['player2_char_name_chosen'] = ai_char
            
            if AI_SID_PLACEHOLDER not in room['players']:
                ai_p_state = get_default_player_state(2, ai_char)
                ai_p_state['sid'] = AI_SID_PLACEHOLDER
                ai_p_state['id'] = 'player2'
                room['players'][AI_SID_PLACEHOLDER] = ai_p_state
            else: 
                room['players'][AI_SID_PLACEHOLDER].update({'character_name': ai_char, 
                                                            'original_character_name': ai_char, 
                                                            'display_character_name': ai_char, 
                                                            'id': 'player2'})
            print(f"🤖 AI (player2) set to {ai_char}")
            room['p2_selection_complete'] = True
            ready_for_controls = True
            
        elif room['game_mode'] == 'TWO':
            # Check if Player 2 is connected for online mode
            player2_connected = any(p['id'] == 'player2' for p in room['players'].values() if p['sid'] != AI_SID_PLACEHOLDER)
            if player2_connected:
                room['current_screen'] = 'CHARACTER_SELECT_P2'
            else:
                print("⏳ Waiting for Player 2 to connect...")
                room['p1_waiting_for_p2'] = True
            
    elif room['current_screen'] == 'CHARACTER_SELECT_P2' and player_data['id'] == 'player2':
        if room['game_mode'] == 'TWO' and room['p1_selection_complete']:
            room['player2_char_name_chosen'] = char_name
            room['p2_selection_complete'] = True
            ready_for_controls = True

    if ready_for_controls:
        room['current_screen'] = 'CONTROLS'
        room['state_timer_ms'] = CONTROLS_SCREEN_DURATION_MS
        print(f"🎯 Setting CONTROLS screen for {room['game_mode']} mode with {CONTROLS_SCREEN_DURATION_MS}ms timer")
    
    socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('player_actions')
def handle_player_actions(data):
    """FIXED: Better action handling with proper walk animation tracking"""
    player_sid = request.sid
    room = game_sessions.get(game_room_id)
    
    if not room or player_sid not in room['players'] or room['current_screen'] not in ['PLAYING', 'SPECIAL']: 
        return
    
    player = room['players'][player_sid]
    if player['health'] <= 0: 
        return
    
    actions = data.get('actions', [])
    action_taken = False
    
    # Skip processing actions during knockback
    if player.get('knockback_timer', 0) > 0:
        return
    
    # Reset movement flag at start of frame
    player['is_moving_this_frame'] = False
    
    for action_data in actions:
        action_type = action_data.get('type')
        
        if action_type == 'move':
            if not player['is_attacking'] and not player['is_ducking']:
                direction = action_data.get('direction')
                if direction == 'left': 
                    player['x'] -= PLAYER_SPEED
                    player['facing'] = -1
                    player['is_moving_this_frame'] = True  # FIXED: Track that we're moving
                elif direction == 'right': 
                    player['x'] += PLAYER_SPEED
                    player['facing'] = 1
                    player['is_moving_this_frame'] = True  # FIXED: Track that we're moving
                
                apply_screen_wrap(player)
                
                # FIXED: Only set walk animation if not doing other actions AND we're actually moving
                if not player['is_jumping'] and not player['is_attacking'] and not player['is_ducking']:
                    player['current_animation'] = 'walk'
                action_taken = True
                
        elif action_type == 'jump':
            if not player['is_jumping'] and not player['is_ducking'] and not player['is_attacking']:
                player['is_jumping'] = True
                player['vertical_velocity'] = PLAYER_JUMP_VELOCITY
                player['current_animation'] = 'jump'
                player['is_ducking'] = False 
                action_taken = True
                
        elif action_type == 'duck':
            is_ducking_cmd = action_data.get('active', False)
            if not player['is_jumping'] and not player['is_attacking']:
                if player['is_ducking'] != is_ducking_cmd: 
                    player['is_ducking'] = is_ducking_cmd
                    player['current_animation'] = 'duck' if is_ducking_cmd else 'idle'
                    action_taken = True
                    
        elif action_type == 'attack':
            if not player['is_attacking'] and player['cooldown_timer'] == 0 and not player['is_ducking']:
                player['is_attacking'] = True
                player['attack_timer'] = ATTACK_DURATION
                player['current_animation'] = 'jump_attack' if player['is_jumping'] else 'attack'
                player['has_hit_this_attack'] = False
                action_taken = True
                print(f"⚔️ {player['id']} attacking! Timer: {player['attack_timer']}")

@socketio.on('change_background')
def handle_background_change(data):
    player_sid = request.sid
    room = game_sessions.get(game_room_id)
    
    if not room or player_sid not in room['players']: 
        return
    
    print(f"🖼️ Background change requested. Current screen: {room['current_screen']}")
    
    if room['current_screen'] == 'PLAYING':
        if not room.get('special_level_active', False):
            old_index = room['current_background_index']
            room['current_background_index'] = (room['current_background_index'] + 1) % PARIS_BG_COUNT
            print(f"🗼 Paris background changed from {old_index} to {room['current_background_index']}")
        else:
            current_church_index = room.get('current_background_index', 0)
            new_church_index = (current_church_index + 1) % CHURCH_BG_COUNT
            room['current_background_index'] = new_church_index
            room['current_background_key'] = 'church'
            print(f"⛪ Special level background changed from {current_church_index} to {new_church_index}")
    elif room['current_screen'] == 'SPECIAL':
        current_church_index = room.get('current_background_index', 0)
        new_church_index = (current_church_index + 1) % CHURCH_BG_COUNT
        room['current_background_index'] = new_church_index
        room['current_background_key'] = 'church'
        print(f"⛪ Special screen background changed from {current_church_index} to {new_church_index}")
    else:
        print(f"🚫 Background change ignored for screen: {room['current_screen']}")
        return
    
    socketio.emit('update_room_state', room, room=game_room_id)

def game_loop_task():
    """Main game loop background task"""
    global last_broadcast_time
    print("🚀 GAME LOOP TASK STARTING!")
    loop_count = 0
    
    try:
        while True:
            try:
                loop_count += 1
                room = game_sessions.get(game_room_id)
                
                if loop_count % 180 == 0:  # Log every 3 seconds
                    if room:
                        print(f"🎮 Status: Screen={room.get('current_screen', 'UNKNOWN')}, Players={len(room.get('players', {}))}")
                
                if room: 
                    current_time = time.time()
                    if current_time - last_broadcast_time >= BROADCAST_INTERVAL:
                        try:
                            game_tick(room)
                            last_broadcast_time = current_time
                        except Exception as tick_error:
                            print(f"❌ ERROR in game_tick: {tick_error}")
                
                socketio.sleep(1 / 120)  # 120 FPS loop
                
            except Exception as loop_error:
                print(f"❌ ERROR in game loop: {loop_error}")
                socketio.sleep(1)
                
    except Exception as fatal_error:
        print(f"💀 FATAL ERROR in game_loop_task: {fatal_error}")

# Global flag to track if game loop is running
game_loop_started = False

def start_game_loop():
    """Start the game loop background task"""
    global game_loop_started
    if game_loop_started:
        print("🔄 Game loop already started, skipping...")
        return True
        
    try:
        print("🎬 Attempting to start background task...")
        socketio.start_background_task(target=game_loop_task)
        game_loop_started = True
        print("✅ Background task started successfully!")
        return True
    except Exception as task_error:
        print(f"❌ FAILED to start background task: {task_error}")
        import traceback
        traceback.print_exc()
        return False

# Production configuration
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🗡️ Kylander: FIXED Edition Server starting on port {port}...")
    print("⚔️ FIXES: 4-second Controls Screen, Proper Mode Selection, Character Choice Flow!")
    
    print("🚀 Starting game loop background task...")
    start_game_loop()
    
    def delayed_start():
        import time
        time.sleep(2)
        print("🔄 Secondary game loop start attempt...")
        start_game_loop()
    
    import threading
    delayed_thread = threading.Thread(target=delayed_start)
    delayed_thread.daemon = True
    delayed_thread.start()
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
