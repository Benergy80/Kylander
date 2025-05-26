from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import random
import time
import os

# Kylander: The Reckoning - Server Code
# FIXED: Ducking stuck bug and balanced AI attack frequency

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
ATTACK_DURATION = 24      # Animation duration for attacks
ATTACK_COOLDOWN = 15      # UPDATED: Shorter cooldown for human players (was 20)
CLASH_STUN_DURATION = 30  # Longer stun for more dramatic effect
KNOCKBACK_DISTANCE = 50   # INCREASED: Very noticeable knockback
MAX_WINS = 5; SPECIAL_LEVEL_WINS = 3 
SLIDESHOW_DURATION_MS = 6000; VICTORY_SCREEN_DURATION_MS = 4000
CONTROLS_SCREEN_DURATION_MS = 1000; CHURCH_INTRO_DURATION_MS = 4000
QUICKENING_FLASHES = 6; QUICKENING_FLASH_DURATION_MS = 100
MAX_PLAYERS_PER_ROOM = 2

PARIS_BG_COUNT = 7; CHURCH_BG_COUNT = 3; VICTORY_BG_COUNT = 10; SLIDESHOW_COUNT = 12
CHARACTER_NAMES = ["The Potzer", "The Kylander", "Darichris"]
AI_SID_PLACEHOLDER = "AI_PLAYER_SID" 

# FIXED: Rebalanced AI constants for better gameplay
AI_SPEED_MULTIPLIER = 0.6  # Movement speed multiplier
AI_PREFERRED_DISTANCE = 75  # REDUCED: From 85 to 75 as requested
AI_DISTANCE_BUFFER = 30     # Distance tolerance
AI_ATTACK_FREQUENCY = 0.12  # REDUCED: From 0.22 to 0.12 (much less frequent attacks)
AI_JUMP_FREQUENCY = 0.15    # Reduced jumping frequency
AI_DUCK_FREQUENCY = 0.18    # REDUCED: From 0.2 to 0.18 (slightly less ducking)
AI_ATTACK_COOLDOWN_BONUS = 60  # INCREASED: From 45 to 60 (even longer AI cooldown)

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
        'knockback_timer': 0,  # NEW: Track knockback state
        'duck_state_sync_timer': 0  # NEW: Track duck state for better sync
    }

def get_default_room_state():
    return {
        'id': game_room_id, 'players': {}, 'current_screen': 'TITLE', 'game_mode': None,
        'player1_char_name_chosen': None, 'player2_char_name_chosen': None,
        'p1_selection_complete': False, 'p2_selection_complete': False,
        'p1_waiting_for_p2': False,  # NEW: Track if P1 is waiting for P2 to connect
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
        'clash_flash_timer': 0,  # NEW: Track clash flash effect
        # ADDED: Track original character for special level reversion
        'special_level_original_p1_char': None,
        'special_level_original_p2_char': None,
        'slideshow_music_started': False,  # Track slideshow music state
        'church_victory_sound_triggered': False,  # Track when to play Darius sound
        'church_victory_bg_index': 0  # NEW: Track which church victory background (0 or 1) for sound selection
    }
game_sessions[game_room_id] = get_default_room_state()

def get_player_by_id(room_state, target_player_id):
    if target_player_id == AI_SID_PLACEHOLDER and AI_SID_PLACEHOLDER in room_state['players']: return room_state['players'][AI_SID_PLACEHOLDER]
    for p_state in room_state['players'].values():
        if p_state['id'] == target_player_id: return p_state
    return None

def get_opponent_state(room_state, player_state_or_sid):
    player_id_to_match = None; current_sid = None
    if isinstance(player_state_or_sid, str): 
        current_sid = player_state_or_sid
        if current_sid in room_state['players']: player_id_to_match = room_state['players'][current_sid]['id']
    elif isinstance(player_state_or_sid, dict): 
        player_id_to_match = player_state_or_sid.get('id'); current_sid = player_state_or_sid.get('sid')
    if player_id_to_match:
        for p_sid_iter, p_data in room_state['players'].items():
            if p_sid_iter != current_sid: return p_data
    return None

def cleanup_room_state(room_state):
    """Clean up any accumulated state that might cause memory issues"""
    for player_sid, player_state in room_state['players'].items():
        if 'miss_swing' in player_state:
            player_state['miss_swing'] = False
        if '_temp_animation_data' in player_state:
            del player_state['_temp_animation_data']
        # Reset knockback
        player_state['knockback_timer'] = 0
        
        # ENHANCED: More aggressive ducking state cleanup
        if player_state.get('is_ducking') and (player_state.get('is_jumping') or player_state.get('is_attacking')):
            print(f"CLEANUP: Resetting stuck ducking state for {player_state.get('id', 'unknown')}")
            player_state['is_ducking'] = False
            player_state['current_animation'] = 'idle'
            player_state['duck_state_sync_timer'] = 0  # Reset sync timer
            
        # ADDITIONAL: Reset ducking if it's been active too long without movement
        if player_state.get('is_ducking') and player_state.get('duck_state_sync_timer', 0) > 120:  # 2 seconds at 60fps
            print(f"TIMEOUT: Resetting long-duration duck for {player_state.get('id', 'unknown')}")
            player_state['is_ducking'] = False
            player_state['current_animation'] = 'idle'
            player_state['duck_state_sync_timer'] = 0
    
    room_state['sfx_event_for_client'] = None
    room_state['swordeffects_playing'] = False
    room_state['clash_flash_timer'] = 0  # Reset clash flash effect
    room_state['church_victory_sound_triggered'] = False  # Reset church victory sound flag
    room_state['church_victory_bg_index'] = 0  # NEW: Reset church victory background index

def reset_player_for_round(player_state, room_state): 
    player_state['health'] = 100
    player_state['x'] = 150 if player_state['id'] == 'player1' else GAME_WIDTH - 150
    player_state['y'] = GROUND_LEVEL
    player_state.update({'is_attacking': False, 'attack_timer': 0, 'cooldown_timer': 0, 'is_jumping': False, 
                         'is_ducking': False, 'vertical_velocity': 0, 'current_animation': 'idle', 
                         'has_hit_this_attack': False, 'is_ready_next_round': False,
                         'facing': 1 if player_state['id'] == 'player1' else -1,
                         'miss_swing': False, 'knockback_timer': 0, 'duck_state_sync_timer': 0})  
    # FIXED: Proper asset swapping for special level
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
            print("🎯 Setting up special level background")
            available_church_bgs = [i for i in range(CHURCH_BG_COUNT) if i not in room_state.get('used_special_bgs', [])]
            if not available_church_bgs: 
                room_state['used_special_bgs'] = []
                available_church_bgs = list(range(CHURCH_BG_COUNT))
            chosen_church_idx = random.choice(available_church_bgs)
            room_state.update({'current_background_key': 'church', 'current_background_index': chosen_church_idx})
            room_state.setdefault('used_special_bgs', []).append(chosen_church_idx)
        else:
            print("🎯 Setting up normal Paris background")
            old_bg_index = room_state.get('current_background_index', -1)
            new_bg_index = (old_bg_index + 1) % PARIS_BG_COUNT
            room_state.update({'current_background_key': 'paris', 'current_background_index': new_bg_index})
            print(f"🎯 Background changed from {old_bg_index} to {new_bg_index}")
        
        room_state['current_screen'] = 'PLAYING'
        print(f"🎯 ✅ initialize_round COMPLETE! Screen set to: {room_state['current_screen']}")
        
    except Exception as e:
        print(f"❌ EXCEPTION in initialize_round: {e}")
        import traceback
        traceback.print_exc()

def handle_round_victory(room_state, victor_player_id, loser_player_id):
    if room_state['current_screen'] not in ['PLAYING', 'SPECIAL']: 
        return
    
    cleanup_room_state(room_state)
    print(f"Round over! Winner: {victor_player_id}")
    
    if victor_player_id == 'player1': room_state['match_score_p1'] += 1
    elif victor_player_id == 'player2': room_state['match_score_p2'] += 1

    # Check for game winner IMMEDIATELY after score update
    if room_state['match_score_p1'] >= MAX_WINS or room_state['match_score_p2'] >= MAX_WINS:
        room_state['game_winner_player_id'] = victor_player_id
        print(f"MATCH WINNER determined: {victor_player_id}")
    
    room_state.update({'round_winner_player_id': victor_player_id, 'quickening_effect_active': True, 
                       'state_timer_ms': (QUICKENING_FLASHES * 2 * QUICKENING_FLASH_DURATION_MS) + 500,
                       'current_screen': room_state['current_screen']}) 

def handle_special_level_loss_by_swapped(room_state, original_victor_id): 
    print(f"Player {original_victor_id} (original character) defeated Darichris (swapped character) in special level!")
    room_state.update({'dark_quickening_effect_active': True, 'game_winner_player_id': original_victor_id,
                       'state_timer_ms': (QUICKENING_FLASHES * 2 * QUICKENING_FLASH_DURATION_MS) + 500,
                       'current_screen': 'SPECIAL_END'})

def end_special_level(room_state):
    """Properly end special level and revert characters"""
    print("Ending special level, reverting characters")
    room_state['special_level_active'] = False
    room_state['special_swap_target_player_id'] = None
    
    # FIXED: Revert characters to their original forms
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
    # Handle knockback - disable ALL movement during knockback
    if player_state.get('knockback_timer', 0) > 0:
        player_state['knockback_timer'] -= 1
        # FIXED: Prevent all input processing during knockback
        player_state['is_attacking'] = False
        player_state['is_ducking'] = False
        # Allow gravity for vertical knockback effect
        if player_state['is_jumping']:
            player_state['y'] += player_state['vertical_velocity']
            player_state['vertical_velocity'] += GRAVITY
            if player_state['y'] >= GROUND_LEVEL:
                player_state.update({'y': GROUND_LEVEL, 'is_jumping': False, 'vertical_velocity': 0})
        return  # Don't process any other movement during knockback
    
    # ENHANCED: Better ducking state management with timeout
    if player_state.get('is_ducking'):
        player_state['duck_state_sync_timer'] = player_state.get('duck_state_sync_timer', 0) + 1
        # Force reset ducking if conflicting states
        if player_state['is_jumping'] or player_state['is_attacking']:
            print(f"FORCE RESET: Ducking disabled due to conflict for {player_state.get('id', 'unknown')}")
            player_state['is_ducking'] = False
            player_state['duck_state_sync_timer'] = 0
            player_state['current_animation'] = 'jump' if player_state['is_jumping'] else ('attack' if player_state['is_attacking'] else 'idle')
        # Timeout protection - max 3 seconds of continuous ducking
        elif player_state['duck_state_sync_timer'] > 180:  # 3 seconds at 60fps
            print(f"TIMEOUT RESET: Ducking disabled due to timeout for {player_state.get('id', 'unknown')}")
            player_state['is_ducking'] = False
            player_state['duck_state_sync_timer'] = 0
            player_state['current_animation'] = 'idle'
    else:
        player_state['duck_state_sync_timer'] = 0
    
    if player_state['is_jumping']:
        player_state['y'] += player_state['vertical_velocity']; player_state['vertical_velocity'] += GRAVITY
        if player_state['y'] >= GROUND_LEVEL:
            player_state.update({'y': GROUND_LEVEL, 'is_jumping': False, 'vertical_velocity': 0})
            if not player_state['is_attacking'] and not player_state['is_ducking']: 
                player_state['current_animation'] = 'idle'
    if player_state['cooldown_timer'] > 0: player_state['cooldown_timer'] -= 1
    if player_state['is_attacking']:
        player_state['attack_timer'] -= 1
        if player_state['attack_timer'] <= 0:
            # FIXED: Check for missed attacks to trigger sound
            if not player_state['has_hit_this_attack']:
                player_state['miss_swing'] = True
            player_state.update({'is_attacking': False, 'has_hit_this_attack': False, 'cooldown_timer': ATTACK_COOLDOWN})
            # Better animation state management after attack
            if player_state['is_jumping']:
                player_state['current_animation'] = 'jump'
            elif player_state['is_ducking']:
                player_state['current_animation'] = 'duck'
            else:
                player_state['current_animation'] = 'idle'

def apply_screen_wrap(player_state):
    if player_state['x'] > GAME_WIDTH + PLAYER_SPRITE_HALF_WIDTH: player_state['x'] = -PLAYER_SPRITE_HALF_WIDTH +1 
    elif player_state['x'] < -PLAYER_SPRITE_HALF_WIDTH: player_state['x'] = GAME_WIDTH + PLAYER_SPRITE_HALF_WIDTH -1

def update_ai(ai_state, target_state, room_state):
    """REBALANCED: AI behavior with reduced attack frequency and better positioning"""
    if not ai_state or not target_state or ai_state['health'] <= 0: return
    update_player_physics_and_timers(ai_state)
    
    # Skip AI updates during knockback
    if ai_state['knockback_timer'] > 0:
        return
    
    # Calculate distance and direction
    dx = target_state['x'] - ai_state['x']
    distance = abs(dx)
    current_time_s = time.time()
    
    # UPDATED: Ducking behavior - slightly less frequent but still defensive
    if (target_state['is_attacking'] and distance < PLAYER_ATTACK_RANGE + 40 and 
        not ai_state['is_jumping'] and random.random() < AI_DUCK_FREQUENCY):
        if current_time_s - ai_state.get('_ai_last_duck_time', 0) > 2.2:  # Slightly longer cooldown
            ai_state.update({'is_ducking': True, 'current_animation': 'duck', 'duck_state_sync_timer': 0})
            ai_state['_ai_last_duck_time'] = current_time_s
    elif ai_state['is_ducking']:
        ai_state['is_ducking'] = False
        if not ai_state['is_attacking'] and not ai_state['is_jumping']:
            ai_state['current_animation'] = 'idle'
    
    # REBALANCED: Much less aggressive attack frequency
    attack_frequency = AI_ATTACK_FREQUENCY  # 0.12 - much more conservative
    if room_state.get('special_level_active') and ai_state.get('display_character_name') == 'Darichris':
        attack_frequency = 0.35  # REDUCED: From 0.55 to 0.35 for special level
    
    # Only attack when in proper range and with longer delays
    if (not ai_state['is_attacking'] and ai_state['cooldown_timer'] == 0 and 
        not ai_state['is_ducking'] and 
        distance >= AI_PREFERRED_DISTANCE - AI_DISTANCE_BUFFER and
        distance <= PLAYER_ATTACK_RANGE + 15):  # Slightly tighter attack range
        if random.random() < attack_frequency:
            ai_state.update({
                'is_attacking': True, 
                'attack_timer': ATTACK_DURATION,
                'current_animation': 'jump_attack' if ai_state['is_jumping'] else 'attack',
                'has_hit_this_attack': False,
                'cooldown_timer': ATTACK_COOLDOWN + AI_ATTACK_COOLDOWN_BONUS  # 15 + 60 = 75 total cooldown
            })
    
    # BALANCED: Movement behavior with new preferred distance (75)
    if not ai_state['is_attacking'] and not ai_state['is_ducking']:
        # Move 70% of the time
        if random.random() >= 0.3:
            # Keep optimal fighting distance
            if distance > AI_PREFERRED_DISTANCE + AI_DISTANCE_BUFFER:
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
            elif distance < AI_PREFERRED_DISTANCE - AI_DISTANCE_BUFFER:
                # Move away to maintain distance
                move_speed = int(PLAYER_SPEED * AI_SPEED_MULTIPLIER)
                if dx > 0:
                    ai_state['x'] -= move_speed
                    ai_state['facing'] = 1
                else:
                    ai_state['x'] += move_speed
                    ai_state['facing'] = -1
                if not ai_state['is_jumping']:
                    ai_state['current_animation'] = 'walk'
            else:
                # In optimal range - just face opponent
                if not ai_state['is_jumping']:
                    ai_state['current_animation'] = 'idle'
                ai_state['facing'] = 1 if dx > 0 else -1
    
    # UPDATED: Conservative jumping for more predictable AI behavior
    if (not ai_state['is_jumping'] and not ai_state['is_ducking'] and 
        random.random() < AI_JUMP_FREQUENCY):
        if current_time_s - ai_state.get('_ai_last_jump_time', 0) > 3.5:  # Even longer jump cooldown
            ai_state.update({
                'is_jumping': True,
                'vertical_velocity': PLAYER_JUMP_VELOCITY,
                'current_animation': 'jump'
            })
            ai_state['_ai_last_jump_time'] = current_time_s
    
    apply_screen_wrap(ai_state)

def game_tick(room_state):
    try:
        # ALWAYS print this to verify game_tick is being called
        current_screen = room_state.get('current_screen', 'UNKNOWN')
        timer_val = room_state.get('state_timer_ms', 0)
        print(f"🔄 game_tick: screen={current_screen}, timer={timer_val:.1f}")
        
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

        # FIXED: Only handle timer once per frame
        if room_state['state_timer_ms'] > 0:
            old_timer = room_state['state_timer_ms']
            room_state['state_timer_ms'] -= delta_s * 1000
            print(f"⏰ Timer: {old_timer:.1f} -> {room_state['state_timer_ms']:.1f} (delta: {delta_s:.3f})")
            
            if room_state['state_timer_ms'] <= 0:
                prev_screen_when_timer_expired = room_state['current_screen'] 
                print(f"🚨 TIMER EXPIRED! Processing screen: {prev_screen_when_timer_expired}")
                
                if room_state['quickening_effect_active'] or room_state['dark_quickening_effect_active']:
                    room_state['quickening_effect_active'] = False; room_state['dark_quickening_effect_active'] = False
                    
                    # FIXED: Handle SPECIAL_END state for dark quickening
                    if prev_screen_when_timer_expired == 'SPECIAL_END':
                        # Show GAME_OVER screen after dark quickening
                        room_state.update({'current_screen': 'GAME_OVER', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                    elif room_state['game_winner_player_id']:
                        if prev_screen_when_timer_expired == 'SPECIAL_END':
                            # Show GAME_OVER screen for special level defeat
                            room_state.update({'current_screen': 'GAME_OVER', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                        else:
                            room_state.update({'current_screen': 'FINAL', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS}) 
                        if not room_state['final_sound_played']: room_state['final_sound_played'] = True 
                    # FIXED: Church victory handling - match original kylander2.py exactly
                    elif prev_screen_when_timer_expired == 'SPECIAL' and \
                         room_state['round_winner_player_id'] == room_state['special_swap_target_player_id']:
                        # Darichris (swapped player) won the special round. Show church victory screen.
                        print("Darichris won special round. Showing church victory screen.")
                        chosen_bg_index = random.choice([0, 1])  # 0 = churchvictory.png, 1 = churchvictory2.png
                        room_state.update({'current_screen': 'CHURCH_VICTORY', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS,
                                          'church_victory_sound_triggered': True, 'church_victory_bg_index': chosen_bg_index})
                        room_state['current_background_index'] = chosen_bg_index
                        print(f"Church victory using background index {chosen_bg_index} ({'churchvictory.png' if chosen_bg_index == 0 else 'churchvictory2.png'})")
                        # FIXED: End special level after Darichris wins
                        end_special_level(room_state)
                    elif prev_screen_when_timer_expired == 'SPECIAL' and \
                         room_state['round_winner_player_id'] != room_state['special_swap_target_player_id']:
                        # Original character won special round. Back to normal gameplay.
                        print("Original character won special round. Showing normal church victory.")
                        room_state.update({'current_screen': 'CHURCH_VICTORY', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS})
                        # Use churchvictory.png (index 0) for original character win
                        room_state['current_background_index'] = 0
                        # FIXED: End special level after original character wins
                        end_special_level(room_state)
                    # FIXED: Special level trigger logic - handle AI opponent winning 3 rounds
                    elif not room_state['special_level_active'] and \
                         (room_state['match_score_p1'] == SPECIAL_LEVEL_WINS or room_state['match_score_p2'] == SPECIAL_LEVEL_WINS) and \
                         room_state['round_winner_player_id']: 
                         room_state['special_level_active'] = True 
                         winner_of_trigger_round = room_state['round_winner_player_id']
                         # Store original characters before swapping
                         p1 = get_player_by_id(room_state, 'player1')
                         p2 = get_player_by_id(room_state, 'player2')
                         if p1: room_state['special_level_original_p1_char'] = p1['original_character_name']
                         if p2: room_state['special_level_original_p2_char'] = p2['original_character_name']
                         
                         # CRITICAL FIX: The LOSER becomes Darichris!
                         if room_state['match_score_p1'] == SPECIAL_LEVEL_WINS:
                             # Player 1 won 3 rounds, so Player 2 (the opponent) becomes Darichris
                             room_state['special_swap_target_player_id'] = 'player2'
                             print(f"Player 1 won 3 rounds. AI opponent (player2) becomes Darichris.")
                         else:
                             # Player 2 (AI) won 3 rounds, so Player 1 becomes Darichris  
                             room_state['special_swap_target_player_id'] = 'player1'
                             print(f"AI opponent (player2) won 3 rounds. Player 1 becomes Darichris.")
                         
                         room_state.update({'current_screen': 'CHURCH_INTRO', 'state_timer_ms': CHURCH_INTRO_DURATION_MS})
                         print(f"Special Level triggered. Winner: {winner_of_trigger_round}. {room_state['special_swap_target_player_id']} becomes Darichris.")
                    else: 
                        room_state.update({'current_screen': 'VICTORY', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS, 'current_background_key': 'victory'})
                        if not room_state.get('available_victory_bgs_player'): room_state['available_victory_bgs_player'] = list(range(VICTORY_BG_COUNT))
                        if room_state['available_victory_bgs_player']:
                            idx = random.choice(room_state['available_victory_bgs_player'])
                            room_state['current_background_index'] = idx; room_state['available_victory_bgs_player'].remove(idx)
                        else: room_state['current_background_index'] = random.randint(0, VICTORY_BG_COUNT -1)
                        
                        if not room_state.get('available_victory_sfx_indices'): room_state['available_victory_sfx_indices'] = list(range(5))
                        if room_state['available_victory_sfx_indices']:
                            sfx_idx = random.choice(room_state['available_victory_sfx_indices'])
                            room_state['victory_sfx_to_play_index'] = sfx_idx
                            room_state['available_victory_sfx_indices'].remove(sfx_idx)
                        else: room_state['victory_sfx_to_play_index'] = random.randint(0,4)
                
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
                    print("🎯 Church intro expired - calling initialize_round!")
                    try:
                        initialize_round(room_state)
                        print(f"✅ Church intro initialize_round completed! New screen: {room_state['current_screen']}")
                    except Exception as init_error:
                        print(f"❌ ERROR in church intro initialize_round: {init_error}")
                        import traceback
                        traceback.print_exc() 
                # FIXED: Church victory timer handling - return to normal gameplay
                elif prev_screen_when_timer_expired == 'CHURCH_VICTORY':
                    # After church victory screen, return to normal gameplay (not special level)
                    print("Church victory screen ended. Returning to normal gameplay.")
                    # Reset special level flags completely
                    room_state['special_level_active'] = False
                    room_state['special_swap_target_player_id'] = None
                    # Clear any special level character tracking
                    room_state['special_level_original_p1_char'] = None
                    room_state['special_level_original_p2_char'] = None
                    # NEW: Reset church victory sound flags
                    room_state['church_victory_sound_triggered'] = False
                    room_state['church_victory_bg_index'] = 0
                    # Initialize a new round in normal gameplay
                    initialize_round(room_state)
                # FIXED: Handle immediate church victory (when Darichris wins in special level)
                elif prev_screen_when_timer_expired == 'CHURCH_VICTORY_IMMEDIATE':
                    # After immediate church victory, return to normal gameplay
                    print("Immediate church victory ended. Returning to normal gameplay.")
                    # NEW: Reset church victory sound flags
                    room_state['church_victory_sound_triggered'] = False
                    room_state['church_victory_bg_index'] = 0
                    # The special level was already ended, just start a new round
                    initialize_round(room_state)
                elif prev_screen_when_timer_expired == 'VICTORY':
                    if not room_state['game_winner_player_id']: initialize_round(room_state)
                elif prev_screen_when_timer_expired == 'FINAL': 
                    room_state.update({'current_screen': 'SLIDESHOW', 'current_background_key': 'slideshow', 
                                       'current_background_index': 0, 'state_timer_ms': SLIDESHOW_DURATION_MS,
                                       'slideshow_music_started': True})
                elif prev_screen_when_timer_expired == 'GAME_OVER':
                    room_state.update({'current_screen': 'SLIDESHOW', 'current_background_key': 'slideshow', 
                                       'current_background_index': 0, 'state_timer_ms': SLIDESHOW_DURATION_MS,
                                       'slideshow_music_started': True})

        # IMPROVED: Slideshow management with better music control
        if room_state['current_screen'] == 'SLIDESHOW':
            if room_state['state_timer_ms'] <= 0:
                # Check if we've shown all slides
                if room_state['current_background_index'] >= SLIDESHOW_COUNT - 1:
                    # Slideshow completed naturally - prepare to return to title
                    print("Slideshow completed naturally - returning to title")
                    room_state['slideshow_music_started'] = False  # Signal to stop slideshow music
                    
                    # Send update to stop music first
                    socketio.emit('update_room_state', room_state, room=game_room_id)
                    
                    # Brief delay to let music stop, then transition
                    room_state['state_timer_ms'] = 200  # 200ms delay
                    room_state['current_screen'] = 'SLIDESHOW_TO_TITLE'  # Intermediate state
                else:
                    # Show next slide
                    room_state['current_background_index'] = (room_state['current_background_index'] + 1) % SLIDESHOW_COUNT
                    room_state['state_timer_ms'] = SLIDESHOW_DURATION_MS
        
        # Handle slideshow completion transition
        elif room_state['current_screen'] == 'SLIDESHOW_TO_TITLE':
            if room_state['state_timer_ms'] <= 0:
                # Now transition to title
                room_state.update({'current_screen': 'TITLE', 'current_background_key': 'paris',
                                   'current_background_index': 0, 'slideshow_music_started': False})
                # Reset game state
                room_state['match_score_p1'] = 0
                room_state['match_score_p2'] = 0
                room_state['final_sound_played'] = False

        if room_state['current_screen'] == 'PLAYING' or room_state['current_screen'] == 'SPECIAL':
            p1 = get_player_by_id(room_state, 'player1'); p2 = get_player_by_id(room_state, 'player2')
            if p1 : update_player_physics_and_timers(p1)
            if p2 :
                if room_state['ai_opponent_active']: update_ai(p2, p1, room_state)
                else: update_player_physics_and_timers(p2)
            
            # FIXED: Handle miss swing sound effects
            if p1 and p1['miss_swing']:
                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'
                p1['miss_swing'] = False
            if p2 and p2['miss_swing']:
                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'
                p2['miss_swing'] = False
                
            if p1 and p2 and p1['health'] > 0 and p2['health'] > 0:
                p1_hit_this_tick = False; p2_hit_this_tick = False
                
                # === COMBAT MECHANICS OVERVIEW ===
                # 1. SWORD CLASH/BLOCK: Both players attacking simultaneously = knockback, stun, clash sound
                # 2. EVASION (Jump/Duck): Avoid damage but NO clash effects (just miss sound)
                # 3. NORMAL HIT: Attack connects = damage and hit sound
                
                # IMPROVED: Enhanced collision detection with centered sprites
                SPRITE_CENTER_OFFSET_X = 0  # Sprites are already centered properly
                SPRITE_CENTER_OFFSET_Y = 25  # Adjust for bottom-aligned sprites
                
                p1_center_x = p1['x'] + SPRITE_CENTER_OFFSET_X
                p1_center_y = p1['y'] - SPRITE_CENTER_OFFSET_Y
                p2_center_x = p2['x'] + SPRITE_CENTER_OFFSET_X
                p2_center_y = p2['y'] - SPRITE_CENTER_OFFSET_Y
                
                # INCREASED: Much more generous clash detection
                CLASH_DETECTION_RANGE = 110  # INCREASED: Even more generous (was 90)
                VERTICAL_CLASH_TOLERANCE = 80  # INCREASED: (was 70)
                
                # IMPROVED: SWORD CLASH DETECTION - Only when both players are actively attacking
                # This is a TRUE BLOCK that causes knockback, stun, and clash effects
                if p1['is_attacking'] and p2['is_attacking'] and \
                   p1['health'] > 0 and p2['health'] > 0 and \
                   abs(p1_center_x - p2_center_x) < CLASH_DETECTION_RANGE and \
                   abs(p1_center_y - p2_center_y) < VERTICAL_CLASH_TOLERANCE:
                    
                    # VERY GENEROUS: Allow clash even with significant timing differences
                    # Check if either player just started attacking or is still attacking
                    p1_attack_active = p1['is_attacking'] and p1['attack_timer'] > 0
                    p2_attack_active = p2['is_attacking'] and p2['attack_timer'] > 0
                    
                    # Allow clash if both are attacking within a very generous window
                    if p1_attack_active and p2_attack_active and not p1['has_hit_this_attack'] and not p2['has_hit_this_attack']:
                        print(f"GENEROUS CLASH! P1 timer: {p1['attack_timer']}, P2 timer: {p2['attack_timer']}, Distance: {abs(p1_center_x - p2_center_x)}")
                        
                        # Block detected - both players avoid damage completely
                        p1.update({'has_hit_this_attack': True, 'cooldown_timer': max(p1['cooldown_timer'], CLASH_STUN_DURATION), 'attack_timer': min(p1['attack_timer'], 3)})
                        p2.update({'has_hit_this_attack': True, 'cooldown_timer': max(p2['cooldown_timer'], CLASH_STUN_DURATION), 'attack_timer': min(p2['attack_timer'], 3)})
                        
                        # Apply stronger knockback
                        old_p1_x, old_p2_x = p1['x'], p2['x']
                        knockback_force = KNOCKBACK_DISTANCE + 10  # Even stronger knockback
                        if p1['x'] < p2['x']:
                            p1['x'] -= knockback_force
                            p2['x'] += knockback_force
                        else:
                            p1['x'] += knockback_force
                            p2['x'] -= knockback_force
                        
                        print(f"STRONG KNOCKBACK! P1: {old_p1_x} -> {p1['x']}, P2: {old_p2_x} -> {p2['x']}")
                        
                        # UPDATED: Longer knockback timers for more noticeable effect
                        p1['knockback_timer'] = 35  # INCREASED
                        p2['knockback_timer'] = 35  # INCREASED
                        
                        # More dramatic vertical bounce
                        if not p1['is_jumping']:
                            p1['vertical_velocity'] = -10  # INCREASED: (was -8)
                            p1['is_jumping'] = True
                        if not p2['is_jumping']:
                            p2['vertical_velocity'] = -10  # INCREASED: (was -8)
                            p2['is_jumping'] = True
                        
                        # Ensure players stay on screen
                        p1['x'] = max(PLAYER_SPRITE_HALF_WIDTH, min(GAME_WIDTH - PLAYER_SPRITE_HALF_WIDTH, p1['x']))
                        p2['x'] = max(PLAYER_SPRITE_HALF_WIDTH, min(GAME_WIDTH - PLAYER_SPRITE_HALF_WIDTH, p2['x']))
                        
                        # Screen flash effect
                        room_state['clash_flash_timer'] = 8  # INCREASED: (was 5)
                        
                        print("GENEROUS CLASH SUCCESSFUL! - TRUE SWORD BLOCK"); room_state['sfx_event_for_client'] = 'sfx_swordClash'
                        
                else:
                    # No sword clash detected - check for individual hits and evasive maneuvers
                    # IMPORTANT: Jump/Duck are EVASION (avoid damage) not BLOCKS (no clash effects)
                    ATTACK_RANGE_EXTENSION = 50  # INCREASED from 42.5 (PLAYER_ATTACK_RANGE / 2)
                    HIT_BOX_WIDTH = 45  # How wide the hit detection is
                    
                    if p1['is_attacking'] and not p1['has_hit_this_attack']:
                        # Calculate attack position extending from sprite edge
                        if p1['facing'] == 1:  # Facing right
                            attack_x = p1_center_x + ATTACK_RANGE_EXTENSION
                        else:  # Facing left
                            attack_x = p1_center_x - ATTACK_RANGE_EXTENSION
                        
                        # Check if attack can potentially hit p2
                        can_hit_p2 = (abs(attack_x - p2_center_x) < HIT_BOX_WIDTH and 
                                     abs(p1_center_y - p2_center_y) < VERTICAL_CLASH_TOLERANCE)
                        
                        if can_hit_p2:
                            # Check for EVASIVE MANEUVERS (duck or jump defense)
                            if p2['is_ducking']:
                                # DUCK EVASION - avoids damage, no clash effects
                                print(f"P2 DUCK EVASION! P2 avoided P1's attack by ducking")
                                p1['has_hit_this_attack'] = True  # Prevent multiple attempts
                                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'  # Miss sound
                            elif p2['is_jumping'] and not p1['is_jumping']:
                                # JUMP EVASION - defender jumping vs ground attacker, avoids damage, no clash effects
                                print(f"P2 JUMP EVASION! P2 avoided P1's ground attack by jumping")
                                p1['has_hit_this_attack'] = True  # Prevent multiple attempts
                                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'  # Miss sound
                            else:
                                # SUCCESSFUL HIT - either both jumping or defender not evading
                                p2['health'] -= 10; p1['has_hit_this_attack'] = True; p1_hit_this_tick = True
                                print(f"P1 HIT P2. P2 Health: {p2['health']} (P1 jumping: {p1['is_jumping']}, P2 jumping: {p2['is_jumping']})")
                                room_state['sfx_event_for_client'] = 'sfx_swordSwing'
                                if p2['health'] <= 0:
                                    # FIXED: Special level logic for AI wins
                                    if room_state['special_level_active']:
                                        if room_state['special_swap_target_player_id'] == 'player2' and p2.get('display_character_name') == "Darichris":
                                            # Darichris was killed - trigger special ending (dark quickening)
                                            print("AI killed Darichris on holy ground! Dark quickening...")
                                            handle_special_level_loss_by_swapped(room_state, 'player1')
                                        else:
                                            # The non-Darichris player was killed - this means Darichris won!
                                            print("Darichris defeated the AI! Church victory...")
                                            chosen_bg_index = random.choice([0, 1])  # 0 = churchvictory.png, 1 = churchvictory2.png
                                            room_state.update({'current_screen': 'CHURCH_VICTORY_IMMEDIATE', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS,
                                                              'church_victory_sound_triggered': True, 'church_victory_bg_index': chosen_bg_index})
                                            room_state['current_background_index'] = chosen_bg_index
                                            room_state['round_winner_player_id'] = 'player2'  
                                            print(f"Immediate church victory using background index {chosen_bg_index} ({'churchvictory.png' if chosen_bg_index == 0 else 'churchvictory2.png'})")
                                            end_special_level(room_state)
                                    else:
                                        handle_round_victory(room_state, 'player1', 'player2')
                    
                    if p2['is_attacking'] and not p2['has_hit_this_attack'] and p1['health'] > 0:
                        # Calculate attack position extending from sprite edge
                        if p2['facing'] == 1:  # Facing right
                            attack_x = p2_center_x + ATTACK_RANGE_EXTENSION
                        else:  # Facing left
                            attack_x = p2_center_x - ATTACK_RANGE_EXTENSION
                        
                        # Check if attack can potentially hit p1
                        can_hit_p1 = (abs(attack_x - p1_center_x) < HIT_BOX_WIDTH and 
                                     abs(p2_center_y - p1_center_y) < VERTICAL_CLASH_TOLERANCE)
                        
                        if can_hit_p1:
                            # Check for EVASIVE MANEUVERS (duck or jump defense)
                            if p1['is_ducking']:
                                # DUCK EVASION - avoids damage, no clash effects
                                print(f"P1 DUCK EVASION! P1 avoided P2's attack by ducking")
                                p2['has_hit_this_attack'] = True  # Prevent multiple attempts
                                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'  # Miss sound
                            elif p1['is_jumping'] and not p2['is_jumping']:
                                # JUMP EVASION - defender jumping vs ground attacker, avoids damage, no clash effects
                                print(f"P1 JUMP EVASION! P1 avoided P2's ground attack by jumping")
                                p2['has_hit_this_attack'] = True  # Prevent multiple attempts
                                room_state['sfx_event_for_client'] = 'sfx_swordWhoosh'  # Miss sound
                            else:
                                # SUCCESSFUL HIT - either both jumping or defender not evading
                                p1['health'] -= 10; p2['has_hit_this_attack'] = True; p2_hit_this_tick = True
                                print(f"P2 HIT P1. P1 Health: {p1['health']} (P1 jumping: {p1['is_jumping']}, P2 jumping: {p2['is_jumping']})")
                                room_state['sfx_event_for_client'] = 'sfx_swordSwing'
                                if p1['health'] <= 0:
                                    # FIXED: Special level logic for AI opponent
                                    if room_state['special_level_active']:
                                        if room_state['special_swap_target_player_id'] == 'player1' and p1.get('display_character_name') == "Darichris":
                                            # Darichris was killed - trigger special ending (dark quickening)
                                            print("AI killed Darichris on holy ground! Dark quickening...")
                                            handle_special_level_loss_by_swapped(room_state, 'player2')
                                        else:
                                            # The non-Darichris player was killed - this means Darichris won!
                                            print("Darichris defeated the AI! Church victory...")
                                            chosen_bg_index = random.choice([0, 1])  # 0 = churchvictory.png, 1 = churchvictory2.png
                                            room_state.update({'current_screen': 'CHURCH_VICTORY_IMMEDIATE', 'state_timer_ms': VICTORY_SCREEN_DURATION_MS,
                                                              'church_victory_sound_triggered': True, 'church_victory_bg_index': chosen_bg_index})
                                            room_state['current_background_index'] = chosen_bg_index
                                            room_state['round_winner_player_id'] = 'player1'  
                                            print(f"Immediate church victory using background index {chosen_bg_index} ({'churchvictory.png' if chosen_bg_index == 0 else 'churchvictory2.png'})")
                                            end_special_level(room_state)
                                    else:
                                        handle_round_victory(room_state, 'player2', 'player1')
                
                # IMPROVED: Sword effects sound matching original
                if p1['is_attacking'] and p2['is_attacking'] and not room_state['swordeffects_playing']:
                    room_state['sfx_event_for_client'] = 'sfx_swordEffects'
                    room_state['swordeffects_playing'] = True
                elif not (p1['is_attacking'] and p2['is_attacking']):
                    room_state['swordeffects_playing'] = False
        
        # Always emit the room state update
        socketio.emit('update_room_state', room_state, room=game_room_id)
        print(f"✅ game_tick completed and broadcasted")
        
    except Exception as e:
        print(f"❌ EXCEPTION in game_tick: {e}")
        import traceback
        traceback.print_exc()

@app.route('/')
def index(): return render_template('index.html')

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

@app.route('/start_game_loop')
def start_game_loop_route():
    """Manual trigger to start game loop if it's not running"""
    try:
        print("🔧 Manual game loop start triggered!")
        result = start_game_loop()
        return {'status': 'success' if result else 'failed', 'timestamp': time.time()}
    except Exception as e:
        print(f"❌ Failed to start game loop manually: {e}")
        return {'status': 'error', 'error': str(e), 'timestamp': time.time()}

@app.route('/tick')
def manual_tick():
    """Manual single game tick for testing"""
    try:
        print("🔧 Manual tick triggered!")
        room = game_sessions.get(game_room_id)
        if room:
            game_tick(room)
            return {'status': 'tick_executed', 'screen': room.get('current_screen'), 'timer': room.get('state_timer_ms'), 'timestamp': time.time()}
        else:
            return {'status': 'no_room', 'timestamp': time.time()}
    except Exception as e:
        print(f"❌ Failed manual tick: {e}")
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'error': str(e), 'timestamp': time.time()}

@socketio.on('connect')
def handle_connect():
    # Try to start game loop when first player connects
    start_game_loop()
    
    player_sid = request.sid; room = game_sessions[game_room_id]
    print(f"Connect attempt: {player_sid}. Current human SIDs: {[s for s, p in room['players'].items() if s != AI_SID_PLACEHOLDER]}")
    human_sids_in_room = [sid for sid in room['players'] if sid != AI_SID_PLACEHOLDER]
    assigned_player_id_str = None
    if not any(p['id'] == 'player1' for sid, p in room['players'].items() if sid != AI_SID_PLACEHOLDER): assigned_player_id_str = "player1"
    elif not any(p['id'] == 'player2' for sid, p in room['players'].items() if sid != AI_SID_PLACEHOLDER) and len(human_sids_in_room) < MAX_PLAYERS_PER_ROOM:
        assigned_player_id_str = "player2"
    if assigned_player_id_str is None:
        print(f"Room full or slot error. SID {player_sid} rejected."); emit('room_full', room=player_sid); disconnect(player_sid); return
    player_id_num = 1 if assigned_player_id_str == "player1" else 2
    player_state = get_default_player_state(player_id_num); player_state['sid'] = player_sid
    if player_state['id'] == 'player1' and room['player1_char_name_chosen']: player_state.update({'character_name': room['player1_char_name_chosen'], 'original_character_name': room['player1_char_name_chosen'], 'display_character_name': room['player1_char_name_chosen']})
    elif player_state['id'] == 'player2' and room['player2_char_name_chosen']: player_state.update({'character_name': room['player2_char_name_chosen'], 'original_character_name': room['player2_char_name_chosen'], 'display_character_name': room['player2_char_name_chosen']})
    room['players'][player_sid] = player_state; join_room(game_room_id)
    print(f"Player {player_state['id']} ({player_sid}) connected. Total SIDs (inc AI): {len(room['players'])}.")
    
    # FIXED: Check if Player 2 is connecting after Player 1 has already chosen
    if player_state['id'] == 'player2' and room['game_mode'] == 'TWO' and \
       room['p1_selection_complete'] and room['current_screen'] == 'CHARACTER_SELECT_P1':
        # Player 2 connected after Player 1 chose, advance to P2 selection
        room['current_screen'] = 'CHARACTER_SELECT_P2'
        room['p1_waiting_for_p2'] = False  # Clear waiting flag
    elif player_state['id'] == 'player2' and room['game_mode'] == 'TWO' and \
         room['p1_selection_complete'] and not room['p2_selection_complete'] and \
         room['current_screen'] != 'CHARACTER_SELECT_P2': 
        room['current_screen'] = 'CHARACTER_SELECT_P2'
    
    emit('assign_player_id', {'playerId': player_state['id'], 'initialRoomState': room}, room=player_sid)
    socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('disconnect')
def handle_disconnect():
    player_sid = request.sid; room = game_sessions.get(game_room_id)
    if room and player_sid in room['players']:
        p_id_disc = room['players'][player_sid]['id']; del room['players'][player_sid]
        print(f"Player {p_id_disc} ({player_sid}) disconnected.")
        if p_id_disc == 'player1' and room['ai_opponent_active']:
            if AI_SID_PLACEHOLDER in room['players']: del room['players'][AI_SID_PLACEHOLDER]; print("AI player removed.")
            room['ai_opponent_active'] = False
        human_players_remaining_sids = [sid for sid in room['players'] if sid != AI_SID_PLACEHOLDER]
        if not human_players_remaining_sids: game_sessions[game_room_id] = get_default_room_state(); print("Room empty, resetting.")
        else: 
            print(f"One player remains. Resetting room to TITLE.")
            room.update({'current_screen': 'TITLE', 'game_mode': None, 'ai_opponent_active': False,
                         'match_score_p1': 0, 'match_score_p2': 0, 'final_sound_played': False,
                         'player1_char_name_chosen':None, 'player2_char_name_chosen':None,
                         'p1_selection_complete':False, 'p2_selection_complete':False, 
                         'p1_waiting_for_p2':False,  # Reset waiting flag
                         'special_level_active': False,
                         'used_special_bgs': [], 'available_victory_sfx_indices': list(range(5))})
            rem_sid = human_players_remaining_sids[0]
            char_of_remaining = room['players'][rem_sid]['original_character_name'] if rem_sid in room['players'] and room['players'][rem_sid] else None
            new_p1_state = get_default_player_state(1, char_of_remaining); new_p1_state['sid'] = rem_sid
            if AI_SID_PLACEHOLDER in room['players']: del room['players'][AI_SID_PLACEHOLDER]
            room['players'] = {rem_sid: new_p1_state}
            room['player1_char_name_chosen'] = char_of_remaining
            emit('assign_player_id', {'playerId': 'player1', 'initialRoomState': room}, room=rem_sid)
        socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('change_game_state')
def on_change_game_state(data):
    new_state = data.get('newState'); room = game_sessions.get(game_room_id); player_sid = request.sid
    if not room or player_sid not in room['players']: return
    print(f"P {room['players'][player_sid]['id']} req state {new_state} from {room['current_screen']}")
    
    # Special handling for slideshow to title transition
    if new_state == 'TITLE_SCREEN': 
        # ENHANCED: Complete music and state reset
        print("TITLE_SCREEN request - performing complete reset")
        room['slideshow_music_started'] = False  # Signal to stop slideshow music
        room['current_screen'] = 'TITLE'  # Force screen change first
        
        # Send immediate state update to stop music
        socketio.emit('update_room_state', room, room=game_room_id)
        
        # Then reset everything
        current_sids_map = {p['id']: sid for sid, p in room['players'].items() if sid != AI_SID_PLACEHOLDER}
        game_sessions[game_room_id] = get_default_room_state(); new_room_state = game_sessions[game_room_id]
        
        # Preserve players but reset their state
        if 'player1' in current_sids_map:
            p1_sid = current_sids_map['player1']; p1_new = get_default_player_state(1); p1_new['sid'] = p1_sid
            new_room_state['players'][p1_sid] = p1_new
            emit('assign_player_id', {'playerId': 'player1', 'initialRoomState': new_room_state}, room=p1_sid)
        if 'player2' in current_sids_map:
            p2_sid = current_sids_map['player2']; p2_new = get_default_player_state(2); p2_new['sid'] = p2_sid
            new_room_state['players'][p2_sid] = p2_new
            emit('assign_player_id', {'playerId': 'player2', 'initialRoomState': new_room_state}, room=p2_sid)
        
        # Clean up AI if present
        if AI_SID_PLACEHOLDER in room['players']:
            del room['players'][AI_SID_PLACEHOLDER]
            room['ai_opponent_active'] = False
        
        room = new_room_state
        room['final_sound_played'] = False
        room['slideshow_music_started'] = False  # Ensure it's false
    
    elif new_state == 'MODE_SELECT' and room['current_screen'] == 'TITLE': room['current_screen'] = 'MODE_SELECT'
    elif new_state == 'CHARACTER_SELECT_P1' and room['current_screen'] == 'MODE_SELECT':
        room.update({'game_mode': data.get('mode'), 'current_screen': 'CHARACTER_SELECT_P1',
                     'p1_selection_complete':False, 'p2_selection_complete':False,
                     'player1_char_name_chosen':None, 'player2_char_name_chosen':None,
                     'p1_waiting_for_p2':False,  # Reset waiting flag
                     'ai_opponent_active': (data.get('mode') == 'ONE')})
        for p_state_sid_iter in list(room['players'].keys()):
            player_obj = room['players'].get(p_state_sid_iter)
            if player_obj: player_obj.update({'character_name': None, 'original_character_name': None, 'display_character_name': None})
    
    socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('player_character_choice')
def on_player_character_choice(data):
    char_name = data.get('characterName'); player_sid = request.sid
    room = game_sessions.get(game_room_id)
    if not room or player_sid not in room['players'] or char_name not in CHARACTER_NAMES: return

    player_data = room['players'][player_sid]
    print(f"Player {player_data['id']} chose {char_name}")
    player_data.update({'character_name': char_name, 'original_character_name': char_name, 'display_character_name': char_name})

    ready_for_controls = False
    if room['current_screen'] == 'CHARACTER_SELECT_P1' and player_data['id'] == 'player1':
        room['player1_char_name_chosen'] = char_name; room['p1_selection_complete'] = True
        if room['game_mode'] == 'ONE':
            room['ai_opponent_active'] = True
            # Exclude P1's choice AND Darichris for normal AI opponent selection
            normal_ai_opponent_pool = [cn for cn in CHARACTER_NAMES if cn != char_name and cn != "Darichris"]
            if not normal_ai_opponent_pool:
                fallback_ai_pool = [cn for cn in CHARACTER_NAMES if cn != char_name]
                ai_char = random.choice(fallback_ai_pool) if fallback_ai_pool else CHARACTER_NAMES[0]
            else:
                ai_char = random.choice(normal_ai_opponent_pool)
            
            room['player2_char_name_chosen'] = ai_char
            
            # Ensure AI player object for P2 exists with the chosen character
            if AI_SID_PLACEHOLDER not in room['players']:
                ai_p_state = get_default_player_state(2, ai_char); ai_p_state['sid'] = AI_SID_PLACEHOLDER
                ai_p_state['id'] = 'player2'
                room['players'][AI_SID_PLACEHOLDER] = ai_p_state
            else: 
                room['players'][AI_SID_PLACEHOLDER].update({'character_name':ai_char, 
                                                            'original_character_name':ai_char, 
                                                            'display_character_name':ai_char, 
                                                            'id': 'player2'})
            print(f"AI (player2) set to {ai_char}")
            room['p2_selection_complete'] = True; ready_for_controls = True
        elif room['game_mode'] == 'TWO':
            # FIXED: In 2-player mode, always advance to P2 selection after P1 chooses
            # Check if P2 is already connected
            player2_connected = any(p['id'] == 'player2' for p in room['players'].values() if p['sid'] != AI_SID_PLACEHOLDER)
            if player2_connected:
                # Player 2 is already connected, advance to P2 selection screen
                room['current_screen'] = 'CHARACTER_SELECT_P2'
            else:
                # Player 2 not connected yet, wait at P1 screen showing waiting message
                # The screen will change to P2 selection when P2 connects
                print("Waiting for Player 2 to connect...")
                room['p1_waiting_for_p2'] = True
            
    elif room['current_screen'] == 'CHARACTER_SELECT_P2' and player_data['id'] == 'player2':
        if room['game_mode'] == 'TWO' and room['p1_selection_complete']:
            room['player2_char_name_chosen'] = char_name; room['p2_selection_complete'] = True
            ready_for_controls = True

    if ready_for_controls:
        room['current_screen'] = 'CONTROLS'
        room['state_timer_ms'] = CONTROLS_SCREEN_DURATION_MS
        print(f"🎯 Setting CONTROLS screen with timer: {CONTROLS_SCREEN_DURATION_MS}ms")  # DEBUG
    socketio.emit('update_room_state', room, room=game_room_id)

@socketio.on('player_actions')
def handle_player_actions(data):
    player_sid = request.sid; room = game_sessions.get(game_room_id)
    if not room or player_sid not in room['players'] or room['current_screen'] not in ['PLAYING', 'SPECIAL']: return
    player = room['players'][player_sid]
    if player['health'] <= 0 : return
    actions = data.get('actions', []); action_taken = False
    
    # Skip processing actions during knockback
    if player.get('knockback_timer', 0) > 0:
        print(f"Player {player['id']} in knockback, ignoring input")
        return
    
    for action_data in actions:
        action_type = action_data.get('type')
        if action_type == 'move':
            if not player['is_attacking'] and not player['is_ducking']:
                direction = action_data.get('direction')
                if direction == 'left': player['x'] -= PLAYER_SPEED; player['facing'] = -1
                elif direction == 'right': player['x'] += PLAYER_SPEED; player['facing'] = 1
                apply_screen_wrap(player) 
                if not player['is_jumping']: player['current_animation'] = 'walk'
                action_taken = True
        elif action_type == 'jump':
            if not player['is_jumping'] and not player['is_ducking'] and not player['is_attacking']:
                player['is_jumping'] = True; player['vertical_velocity'] = PLAYER_JUMP_VELOCITY
                player['current_animation'] = 'jump'; player['is_ducking'] = False  # FIXED: Explicitly reset ducking
                player['duck_state_sync_timer'] = 0  # Reset duck timer
                action_taken = True
        elif action_type == 'duck':
            is_ducking_cmd = action_data.get('active', False)
            if not player['is_jumping'] and not player['is_attacking']:
                # ENHANCED: Much more explicit ducking state management with logging
                old_ducking_state = player['is_ducking']
                player['is_ducking'] = is_ducking_cmd
                if is_ducking_cmd:
                    player['duck_state_sync_timer'] = 0  # Reset timer when starting to duck
                    player['current_animation'] = 'duck'
                else:
                    player['duck_state_sync_timer'] = 0  # Reset timer when stopping duck
                    player['current_animation'] = 'idle'
                
                if old_ducking_state != is_ducking_cmd:
                    action_taken = True
                    print(f"DUCK ACTION: Player {player['id']} ducking: {old_ducking_state} -> {is_ducking_cmd}")
        elif action_type == 'attack':
            if not player['is_attacking'] and player['cooldown_timer'] == 0 and not player['is_ducking']:
                player['is_attacking'] = True; player['attack_timer'] = ATTACK_DURATION
                player['current_animation'] = 'jump_attack' if player['is_jumping'] else 'attack'
                player['has_hit_this_attack'] = False; player['is_ducking'] = False  # FIXED: Explicitly reset ducking
                player['duck_state_sync_timer'] = 0  # Reset duck timer
                action_taken = True
    
    # ENHANCED: Final safety check with better logging
    if not action_taken and not player['is_jumping'] and not player['is_attacking'] and \
       not player['is_ducking'] and player['current_animation'] not in ['idle', 'jump', 'duck', 'attack', 'jump_attack']:
        print(f"SAFETY: Resetting animation to idle for {player['id']} (was: {player['current_animation']})")
        player['current_animation'] = 'idle'
    
    # ADDITIONAL SAFETY: Reset animation if state doesn't match with more aggressive checking
    if not player['is_ducking'] and player['current_animation'] == 'duck':
        print(f"SAFETY: Resetting duck animation for {player['id']} (not ducking but animation stuck)")
        player['current_animation'] = 'idle' if not player['is_jumping'] and not player['is_attacking'] else player['current_animation']
        player['duck_state_sync_timer'] = 0

# IMPROVED: Background change functionality
@socketio.on('change_background')
def handle_background_change(data):
    player_sid = request.sid; room = game_sessions.get(game_room_id)
    if not room or player_sid not in room['players']: 
        print(f"Background change failed: room={room is not None}, player={player_sid in room.get('players', {})}")
        return
    
    print(f"Background change requested. Current screen: {room['current_screen']}, Special level: {room.get('special_level_active', False)}")
    
    # FIXED: Allow background change during gameplay, including special level (but in a limited way)
    if room['current_screen'] == 'PLAYING':
        if not room.get('special_level_active', False):
            # Normal gameplay - cycle through Paris backgrounds
            old_index = room['current_background_index']
            room['current_background_index'] = (room['current_background_index'] + 1) % PARIS_BG_COUNT
            print(f"Paris background changed from {old_index} to {room['current_background_index']}")
        else:
            # Special level - cycle through Church backgrounds
            current_church_index = room.get('current_background_index', 0)
            new_church_index = (current_church_index + 1) % CHURCH_BG_COUNT
            room['current_background_index'] = new_church_index
            room['current_background_key'] = 'church'  # Ensure it stays church
            print(f"Special level background changed from {current_church_index} to {new_church_index}")
    elif room['current_screen'] == 'SPECIAL':
        # Also allow background change during special screen state
        current_church_index = room.get('current_background_index', 0)
        new_church_index = (current_church_index + 1) % CHURCH_BG_COUNT
        room['current_background_index'] = new_church_index
        room['current_background_key'] = 'church'  # Ensure it stays church
        print(f"Special screen background changed from {current_church_index} to {new_church_index}")
    else:
        print(f"Background change ignored for screen: {room['current_screen']}")
        return
    
    print(f"Broadcasting background change: {room['current_background_key']} {room['current_background_index']}")
    socketio.emit('update_room_state', room, room=game_room_id)

def game_loop_task():
    global last_broadcast_time
    print("🚀 GAME LOOP TASK STARTING!")
    print("🚀 GAME LOOP TASK STARTING!")  # Double print to make it obvious
    loop_count = 0
    
    try:
        while True:
            try:
                loop_count += 1
                room = game_sessions.get(game_room_id)
                
                # Debug: Print every 60 loops (about once per second)
                if loop_count % 60 == 0:
                    if room:
                        print(f"🎮 Loop {loop_count}: Screen={room.get('current_screen', 'UNKNOWN')}, Timer={room.get('state_timer_ms', 0):.1f}, Players={len(room.get('players', {}))}")
                    else:
                        print(f"🎮 Loop {loop_count}: NO ROOM FOUND!")
                
                if room: 
                    current_time = time.time()
                    # Only broadcast at 60 FPS max
                    if current_time - last_broadcast_time >= BROADCAST_INTERVAL:
                        try:
                            game_tick(room)
                            last_broadcast_time = current_time
                        except Exception as tick_error:
                            print(f"❌ ERROR in game_tick: {tick_error}")
                            import traceback
                            traceback.print_exc()
                
                socketio.sleep(1 / 120)  # Sleep for half the target FPS
                
            except Exception as loop_error:
                print(f"❌ ERROR in game loop: {loop_error}")
                import traceback
                traceback.print_exc()
                socketio.sleep(1)  # Wait before retrying
                
    except Exception as fatal_error:
        print(f"💀 FATAL ERROR in game_loop_task: {fatal_error}")
        import traceback
        traceback.print_exc()

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
    print(f"Server starting on port {port}...")
    
    # AGGRESSIVE: Try to start the game loop multiple times
    print("🚀 AGGRESSIVE: Attempting to start game loop background task multiple ways...")
    
    # Method 1: Start before server
    print("Method 1: Starting before server...")
    start_game_loop()
    
    # Method 2: Start after a delay
    def delayed_start():
        import time
        time.sleep(2)  # Wait for server to be ready
        print("Method 2: Delayed start...")
        start_game_loop()
    
    # Start the server
    print("🎯 Starting SocketIO server...")
    
    # Start the delayed task
    import threading
    delayed_thread = threading.Thread(target=delayed_start)
    delayed_thread.daemon = True
    delayed_thread.start()
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
