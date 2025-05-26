const gameCanvas = document.getElementById('gameCanvas');
const ctx = gameCanvas.getContext('2d');

const GAME_WIDTH = 800;
const GAME_HEIGHT = 600;
gameCanvas.width = GAME_WIDTH;
gameCanvas.height = GAME_HEIGHT;

// CHANGED: Sprite scale to 0.875
const SPRITE_SCALE = 0.875; 
const SERVER_ATTACK_DURATION = 24;  // INCREASED: Match server value (was 18)
const WALK_ANIMATION_MS_PER_FRAME = 133; 
const QUICKENING_FLASH_DURATION_MS_CLIENT = 100; 

const socket = io();

let localPlayerId = null;
let roomState = {};
let allAssetsLoaded = false;
let currentMusic = null;
let requestAnimationFrameId;
let mainMusicPlaying = false; 
let roundVictorySfxPlayed = false;
let finalVictorySfxPlayedClient = false;
let musicInitialized = false;

// NEW: Add blinking effect for title screen
let titleBlinkTimer = 0;
const TITLE_BLINK_SPEED = 1000; // milliseconds

const ASSET_PATHS = {
    ui: {
        titleScreen: 'static/assets/ui/title_screen.png',
        quickening: 'static/assets/ui/Quickening.png',
        // FIXED: Try both cases for dark quickening
        darkQuickening: 'static/assets/ui/darkquickening.png',
        darkQuickeningAlt: 'static/assets/ui/DarkQuickening.png',  // Alternative casing
        churchVictory1: 'static/assets/ui/churchvictory.png',
        churchVictory2: 'static/assets/ui/churchvictory2.png',
        victoryBadge: 'static/assets/ui/victorybadge.png',
        gameOver: 'static/assets/ui/GameOver.png',          
        churchIntro: 'static/assets/ui/churchintro.png',       
        characterSelectBg: 'static/assets/ui/characterselect.png' 
    },
    backgrounds: {
        paris: Array.from({length: 7}, (_, i) => `static/assets/backgrounds/paris_bg${i === 0 ? '' : i+1}.png`),
        church: Array.from({length: 3}, (_, i) => `static/assets/backgrounds/church_bg${i+1}.png`),
        victory: Array.from({length: 10}, (_, i) => `static/assets/backgrounds/victory_bg${i === 0 ? '' : i+1}.png`),
        slideshow: Array.from({length: 12}, (_, i) => `static/assets/backgrounds/slideshow_${i+1}.png`),
        // Church victory should use UI assets
        church_victory: [
            'static/assets/ui/churchvictory.png',
            'static/assets/ui/churchvictory2.png' 
        ]
    },
    characters: {
        "The Potzer": { idle: "static/assets/sprites/fighter1/fighter1.png", duck: "static/assets/sprites/fighter1/fighter1duck.png", jump: "static/assets/sprites/fighter1/fighter1jump.png", jump_attack: "static/assets/sprites/fighter1/fighter1jumpattack.png", attack_prefix: "static/assets/sprites/fighter1/fighter1slash", num_attack: 3, walk_prefix: "static/assets/sprites/fighter1/fighter1walk",   num_walk: 2, name: "The Potzer" },
        "The Kylander": { idle: "static/assets/sprites/fighter2/fighter2.png", duck: "static/assets/sprites/fighter2/fighter2duck.png", jump: "static/assets/sprites/fighter2/fighter2jump.png", jump_attack: "static/assets/sprites/fighter2/fighter2jumpattack.png", attack_prefix: "static/assets/sprites/fighter2/fighter2slash", num_attack: 3, walk_prefix: "static/assets/sprites/fighter2/fighter2walk",   num_walk: 2, name: "The Kylander" },
        "Darichris": { idle: "static/assets/sprites/fighter3/fighter3.png", duck: "static/assets/sprites/fighter3/fighter3duck.png", jump: "static/assets/sprites/fighter3/fighter3jump.png", jump_attack: "static/assets/sprites/fighter3/fighter3jumpattack.png", attack_prefix: "static/assets/sprites/fighter3/fighter3slash", num_attack: 3, walk_prefix: "static/assets/sprites/fighter3/fighter3walk",   num_walk: 2, name: "Darichris" }
    },
    sfx: { 
        swordClash: "static/assets/sfx/sword_clash.wav", 
        swordSwing: "static/assets/sfx/sword_swing.wav", 
        swordWhoosh: "static/assets/sfx/sword_whoosh.wav", 
        swordEffects: "static/assets/sfx/swordeffects.wav", 
        victoryKurgan: "static/assets/sfx/kurgan_speak_not.wav", 
        victoryBurnOut: "static/assets/sfx/better_to_burn_out.wav", 
        victoryGoat: "static/assets/sfx/highlander_goat.wav", 
        victoryDuncan: "static/assets/sfx/Duncan_did_you_come.wav", 
        victoryKalas: "static/assets/sfx/Kalas_Nothing_Changes.wav", 
        finalVictory: "static/assets/sfx/there_can_be_only_one.wav",
        darius1: "static/assets/sfx/Darius1.mp3",  // NEW: Darius sound for churchvictory2.png (index 1)
        darius2: "static/assets/sfx/Darius2.mp3"   // NEW: Darius sound for churchvictory.png (index 0)
    },
    music: { 
        music_backgroundMusic: "static/assets/music/background_music.mp3",
        music_slideshowMusic: "static/assets/music/background_music2.mp3"
    }
};

const loadedAssets = { images: {}, sounds: {} };
let assetsToLoad = 0, assetsLoaded = 0;
const clientPlayerAnimationState = {};

// FIXED: Track dark quickening alternative
let darkQuickeningLoaded = false;

function loadImage(path, key) {
    return new Promise((resolve) => {
        const img = new Image();
        img.src = path;
        img.onload = () => { 
            loadedAssets.images[key] = img; 
            assetsLoaded++;
            // FIXED: Map alternative dark quickening
            if (key === 'ui_darkQuickeningAlt' && !darkQuickeningLoaded) {
                loadedAssets.images['ui_darkQuickening'] = img;
                darkQuickeningLoaded = true;
            }
            resolve(img); 
        };
        img.onerror = (err) => { 
            console.error(`IMAGE LOAD FAIL: ${path} (key: ${key})`, err); 
            assetsLoaded++; 
            // FIXED: Try alternative case for dark quickening
            if (key === 'ui_darkQuickening' && !darkQuickeningLoaded) {
                console.log("Trying alternative casing for dark quickening...");
                loadImage(ASSET_PATHS.ui.darkQuickeningAlt, 'ui_darkQuickeningAlt');
            }
            resolve(null); 
        };
    });
}

function loadSound(path, key) {
    return new Promise((resolve) => {
        try {
            const audio = new Audio(path); loadedAssets.sounds[key] = audio; assetsLoaded++; resolve(audio);
        } catch (err) { console.error(`SOUND LOAD FAIL: ${path} (key: ${key})`, err); assetsLoaded++; resolve(null); }
    });
}

function loadAllAssets() {
    const promises = []; assetsToLoad = 0; assetsLoaded = 0; allAssetsLoaded = false;
    for (const key in ASSET_PATHS.ui) { 
        if (key !== 'darkQuickeningAlt') {  // Skip alternative, we'll load it only if needed
            assetsToLoad++; 
            promises.push(loadImage(ASSET_PATHS.ui[key], `ui_${key}`)); 
        }
    }
    for (const category in ASSET_PATHS.backgrounds) {
        ASSET_PATHS.backgrounds[category].forEach((bgPath, index) => {
            assetsToLoad++; promises.push(loadImage(bgPath, `bg_${category}_${index}`));
        });
    }
    for (const charKey in ASSET_PATHS.characters) {
        const charData = ASSET_PATHS.characters[charKey];
        assetsToLoad++; promises.push(loadImage(charData.idle, `char_${charKey}_idle`));
        assetsToLoad++; promises.push(loadImage(charData.duck, `char_${charKey}_duck`));
        assetsToLoad++; promises.push(loadImage(charData.jump, `char_${charKey}_jump`));
        assetsToLoad++; promises.push(loadImage(charData.jump_attack, `char_${charKey}_jump_attack`));
        for (let i = 0; i < charData.num_attack; i++) {
            assetsToLoad++; promises.push(loadImage(`${charData.attack_prefix}_${i+1}.png`, `char_${charKey}_attack_${i}`));
        }
        for (let i = 0; i < charData.num_walk; i++) {
            assetsToLoad++; promises.push(loadImage(`${charData.walk_prefix}_${i+1}.png`, `char_${charKey}_walk_${i}`));
        }
    }
    for (const key in ASSET_PATHS.sfx) { assetsToLoad++; promises.push(loadSound(ASSET_PATHS.sfx[key], `sfx_${key}`));}
    for (const musicAssetKey in ASSET_PATHS.music) { 
        assetsToLoad++; 
        promises.push(loadSound(ASSET_PATHS.music[musicAssetKey], musicAssetKey)); 
    }
    console.log(`Attempting to load ${assetsToLoad} assets.`);
    return Promise.all(promises);
}

function drawLoadingScreen() {
    ctx.fillStyle = 'black'; ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
    ctx.fillStyle = 'white'; ctx.font = '20px HighlanderFont, Arial'; ctx.textAlign = 'center';
    const progress = assetsToLoad > 0 ? Math.min(100, (assetsLoaded / assetsToLoad) * 100) : 100;
    ctx.fillText(`Loading Assets... ${Math.round(progress)}%`, GAME_WIDTH / 2, GAME_HEIGHT / 2);
    ctx.textAlign = 'left';
    if (assetsLoaded >= assetsToLoad && !allAssetsLoaded) { allAssetsLoaded = true; console.log("All assets loading initiated.");}
}

// IMPROVED: Better playMusic function with forced restart
function playMusic(musicAssetKey) {
    const targetMusic = loadedAssets.sounds[musicAssetKey];
    if (!targetMusic) { console.warn(`Music asset key "${musicAssetKey}" not found.`); return; }
    
    console.log(`Attempting to play music: ${musicAssetKey}`);
    
    // Always stop current music first if switching tracks
    if (currentMusic && currentMusic.src !== targetMusic.src) {
        console.log("Stopping current music before switching");
        currentMusic.pause(); 
        currentMusic.currentTime = 0;
        currentMusic = null;
    }
    
    // If it's the same track and already playing, don't restart unless explicitly switching
    if (currentMusic && currentMusic.src === targetMusic.src && !currentMusic.paused) {
        console.log("Same music already playing, keeping it");
        mainMusicPlaying = (musicAssetKey === 'music_backgroundMusic');
        return; 
    }
    
    // Start the new music
    targetMusic.loop = true; 
    targetMusic.volume = 0.3; 
    console.log(`Starting music: ${musicAssetKey}`);
    targetMusic.play().then(() => {
        console.log(`Music started successfully: ${musicAssetKey}`);
        currentMusic = targetMusic;
        mainMusicPlaying = (musicAssetKey === 'music_backgroundMusic');
        musicInitialized = true;
    }).catch(e => {
        console.warn("Error playing music:", e);
        // Try again after a brief delay
        setTimeout(() => {
            targetMusic.play().catch(e2 => console.warn("Second attempt failed:", e2));
        }, 100);
    });
}

function stopMusic() { 
    if (currentMusic) { 
        currentMusic.pause(); 
        currentMusic.currentTime = 0; 
    }
    mainMusicPlaying = false;
}

// FIXED: Enhanced title screen with larger font and blinking text
function drawTitleScreen() {
    const titleImg = loadedAssets.images['ui_titleScreen'];
    if (titleImg) ctx.drawImage(titleImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    else { 
        ctx.fillStyle = 'black'; 
        ctx.fillRect(0,0,GAME_WIDTH,GAME_HEIGHT); 
        ctx.fillStyle='white'; 
        ctx.font='40px HighlanderFont, Arial Black'; // Increased font size
        ctx.textAlign='center';
        ctx.fillText("Kylander",GAME_WIDTH/2,GAME_HEIGHT/3); 
    }
    
    // BLINKING EFFECT for "Press Enter to Start"
    titleBlinkTimer += 16; // Approximate 60fps
    const shouldShow = Math.floor(titleBlinkTimer / TITLE_BLINK_SPEED) % 2 === 0;
    
    if (shouldShow) {
        ctx.font='32px HighlanderFont, Arial Black'; // Increased font size
        ctx.fillStyle='white'; 
        ctx.textAlign='center';
        ctx.strokeStyle='black';
        ctx.lineWidth=3; // Thicker outline
        ctx.shadowColor = "rgba(0,0,0,0.8)"; 
        ctx.shadowBlur = 8; 
        ctx.shadowOffsetX = 3; 
        ctx.shadowOffsetY = 3;
        ctx.strokeText("Press Enter to Start", GAME_WIDTH/2, GAME_HEIGHT-100);
        ctx.fillText("Press Enter to Start", GAME_WIDTH/2, GAME_HEIGHT-100);
        ctx.shadowBlur = 0; 
        ctx.shadowOffsetX = 0; 
        ctx.shadowOffsetY = 0; 
    }
    ctx.textAlign='left';
}

// IMPROVED: Show connection instructions for 2-player mode
function drawModeSelectScreen() {
    ctx.fillStyle = 'black'; ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
    ctx.font = '45px HighlanderFont, Arial Black';  // INCREASED: 1.5x (30 -> 45)
    ctx.fillStyle = 'white'; ctx.textAlign = 'center';
    ctx.shadowColor = "rgba(0,0,0,0.7)"; ctx.shadowBlur = 5; ctx.shadowOffsetX = 2; ctx.shadowOffsetY = 2;
    ctx.fillText("Select Mode", GAME_WIDTH / 2, GAME_HEIGHT / 4);
    ctx.font = '36px HighlanderFont, Arial';  // INCREASED: 1.5x (24 -> 36)
    ctx.fillText("Press 1 for One-Player", GAME_WIDTH / 2, GAME_HEIGHT / 2 - 30);
    ctx.fillText("Press 2 for Two-Player", GAME_WIDTH / 2, GAME_HEIGHT / 2 + 30);
    
    // NEW: Add instructions for 2-player mode
    ctx.font = '20px HighlanderFont, Arial';
    ctx.fillStyle = 'lightgray';
    ctx.fillText("For Two-Player: Player 2 opens another browser", GAME_WIDTH / 2, GAME_HEIGHT / 2 + 120);
    ctx.fillText("window to the same URL to connect", GAME_WIDTH / 2, GAME_HEIGHT / 2 + 145);
    
    ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; ctx.textAlign = 'left';
}

// IMPROVED: Larger font for character selection with waiting message
function drawCharacterSelectScreen() {
    const bgImg = loadedAssets.images['ui_characterSelectBg'];
    if (bgImg) ctx.drawImage(bgImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    else { ctx.fillStyle = 'black'; ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT); }
    ctx.fillStyle = 'white'; ctx.textAlign = 'center';
    
    // FIXED: Handle Player 1 waiting for Player 2 to connect
    if (roomState.current_screen === 'CHARACTER_SELECT_P1' && roomState.game_mode === 'TWO' && 
        roomState.p1_selection_complete && roomState.p1_waiting_for_p2) {
        // Show waiting message
        ctx.font = '36px HighlanderFont, Arial Black'; 
        ctx.shadowColor = "rgba(0,0,0,0.8)"; ctx.shadowBlur = 8; ctx.shadowOffsetX = 3; ctx.shadowOffsetY = 3;
        ctx.fillText(`Player 1 has chosen: ${roomState.player1_char_name_chosen}`, GAME_WIDTH / 2, 180);
        
        ctx.font = '30px HighlanderFont, Arial Black';
        ctx.fillText("Waiting for Player 2 to connect...", GAME_WIDTH / 2, 280);
        
        // Show connection instructions
        ctx.font = '22px HighlanderFont, Arial';
        ctx.fillStyle = 'lightgray';
        ctx.fillText("Player 2: Open a new browser window/tab", GAME_WIDTH / 2, 340);
        ctx.fillText(`and go to: ${window.location.href}`, GAME_WIDTH / 2, 365);
        
        ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; ctx.textAlign = 'left';
        return;
    }
    
    const selectingPlayer = roomState.current_screen === 'CHARACTER_SELECT_P1' ? 'Player 1' : 'Player 2';
    ctx.font = '36px HighlanderFont, Arial Black'; 
    ctx.shadowColor = "rgba(0,0,0,0.8)"; ctx.shadowBlur = 8; ctx.shadowOffsetX = 3; ctx.shadowOffsetY = 3;
    ctx.fillText(`${selectingPlayer}, Choose Your Fighter:`, GAME_WIDTH / 2, 100);

    const characterKeys = Object.keys(ASSET_PATHS.characters);
    const textBlockHeight = 60; 
    const totalOptionHeight = textBlockHeight + 60;
    const totalBlockHeightForAllChars = characterKeys.length * totalOptionHeight;
    let startYText = (GAME_HEIGHT - totalBlockHeightForAllChars) / 2 + textBlockHeight / 2 + 50; 

    characterKeys.forEach((charKey, index) => {
        const charData = ASSET_PATHS.characters[charKey];
        const optionY = startYText + index * totalOptionHeight;
        ctx.font = '35px HighlanderFont, Arial Black';  // INCREASED: Larger font for options
        ctx.fillText(`Press ${index + 1} for ${charData.name}`, GAME_WIDTH / 2, optionY);
    });
    ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; ctx.textAlign = 'left';
}

// FIXED: Controls screen with bigger text
function drawControlsScreen() {
    ctx.fillStyle = 'black'; ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
    ctx.fillStyle = 'white'; ctx.font = '42px HighlanderFont, Arial Black'; ctx.textAlign = 'center'; // INCREASED from 28px to 42px
    ctx.shadowColor = "rgba(0,0,0,0.7)"; ctx.shadowBlur = 5; ctx.shadowOffsetX = 2; ctx.shadowOffsetY = 2;
    let lines = [];
    if (roomState.game_mode === "ONE") {
        lines = ["Controls:", "Player 1:", "ARROWS = Move, Jump, Duck", "SPACE = Attack"];
    } else {
        lines = ["Controls:", "Player 1:", "A/D = Move, W = Jump, S = Duck", "Q/E = Attack", "",
                 "Player 2:", "Arrows = Move, Up = Jump, Down = Duck", "Enter = Attack"];
    }
    lines.forEach((line, index) => { ctx.fillText(line, GAME_WIDTH / 2, 120 + index * 55); }); // INCREASED spacing from 40 to 55
    ctx.font = '28px HighlanderFont, Arial'; // INCREASED from 20px to 28px
    ctx.fillText("Starting in a moment...", GAME_WIDTH / 2, GAME_HEIGHT - 50);
    ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; ctx.textAlign = 'left';
}

function drawTopPlayerUI(playerState, x, y, isRightAligned = false) {
    const charNameForUI = playerState?.display_character_name || 
                          (playerState?.id === 'player1' ? (roomState?.player1_char_name_chosen || 'Player 1') : 
                          (roomState?.player2_char_name_chosen || (roomState?.ai_opponent_active ? 'AI' : 'Player 2')));
    const healthForUI = playerState?.health ?? 100;
    const scoreForUI = playerState?.id === 'player1' ? (roomState?.match_score_p1 ?? 0) : (roomState?.match_score_p2 ?? 0);

    const barWidth = 200; const barHeight = 20;
    const nameYOffset = -5; 
    const badgeYOffset = barHeight + 5; 
    const badgeSize = 15 * SPRITE_SCALE; 
    const badgeGap = 4 * SPRITE_SCALE;

    ctx.font = `bold ${Math.floor(16 * SPRITE_SCALE)}px HighlanderFont, Arial Black`; 
    ctx.fillStyle = 'white';
    ctx.shadowColor = "black"; ctx.shadowBlur = 3; ctx.shadowOffsetX = 1; ctx.shadowOffsetY = 1;

    const textX = isRightAligned ? x + barWidth : x;
    ctx.textAlign = isRightAligned ? 'right' : 'left';
    // FIXED: Display character names in ALL CAPS
    ctx.fillText(charNameForUI.toUpperCase(), textX, y + nameYOffset);
    
    ctx.fillStyle = '#33333390'; ctx.fillRect(x, y, barWidth, barHeight);
    const healthFill = (healthForUI / 100) * barWidth;
    ctx.fillStyle = healthForUI > 50 ? 'green' : healthForUI > 25 ? 'yellow' : 'red';
    ctx.fillRect(x, y, healthFill > 0 ? healthFill : 0, barHeight);
    ctx.strokeStyle = 'white'; ctx.lineWidth = 2; ctx.strokeRect(x, y, barWidth, barHeight);

    const badgeImg = loadedAssets.images['ui_victoryBadge'];
    if (badgeImg) {
        for (let i = 0; i < scoreForUI; i++) {
            const badgeX = isRightAligned ? (x + barWidth) - (i + 1) * (badgeSize + badgeGap) - badgeSize/2 : x + i * (badgeSize + badgeGap) + badgeSize/2;
            ctx.drawImage(badgeImg, badgeX - badgeSize/2 , y + badgeYOffset, badgeSize, badgeSize);
        }
    }
    ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
    ctx.textAlign = 'left'; 
}

// FIXED: Added SPECIAL_END state handling
function drawPlayingScreen() {
    // IMPROVED: Special level screen handling
    const bgCategory = roomState.special_level_active ? 'church' : (roomState.current_background_key || 'paris');
    const bgIndex = roomState.current_background_index || 0;
    const bgKey = `bg_${bgCategory}_${bgIndex}`;
    const bgImg = loadedAssets.images[bgKey] || loadedAssets.images['bg_paris_0'];
    if (bgImg) ctx.drawImage(bgImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    else { ctx.fillStyle = 'grey'; ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT); }

    // FIXED: Show B key instruction during both normal and special gameplay
    ctx.font = '16px HighlanderFont, Arial';
    ctx.fillStyle = 'white';
    ctx.shadowColor = "black";
    ctx.shadowBlur = 2;
    ctx.shadowOffsetX = 1;
    ctx.shadowOffsetY = 1;
    if (roomState.special_level_active) {
        ctx.fillText("Press B to change church background", 10, GAME_HEIGHT - 10);
    } else {
        ctx.fillText("Press B to change background", 10, GAME_HEIGHT - 10);
    }
    ctx.shadowBlur = 0;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;

    drawTopPlayerUI(Object.values(roomState.players || {}).find(p => p.id === 'player1'), 30, 30);
    drawTopPlayerUI(Object.values(roomState.players || {}).find(p => p.id === 'player2'), GAME_WIDTH - 200 - 30, 30, true);

    const fightersToDraw = [];
    if (roomState.players) {
        Object.values(roomState.players).forEach(p_state => {
            if (p_state.character_name && ASSET_PATHS.characters[p_state.character_name]) {
                 fightersToDraw.push(p_state);
            }
        });
    }
    fightersToDraw.sort((a, b) => a.y - b.y);

    fightersToDraw.forEach(player => {
        const charKey = player.character_name; 
        const charDataClient = ASSET_PATHS.characters[charKey];
        if (!charDataClient) { return; } 

        let currentImageKey = ''; 
        let frameIndex = 0; 
        
        if (!clientPlayerAnimationState[player.id]) {
            clientPlayerAnimationState[player.id] = { walk_frame: 0, walk_timer: 0 };
        }
        const animState = clientPlayerAnimationState[player.id];

        // IMPROVED: Better animation frame synchronization
        if (player.is_attacking) {
            if (player.is_jumping) {
                // JUMP ATTACK - use jump_attack sprite
                currentImageKey = `char_${charKey}_jump_attack`;
            } else {
                // NORMAL ATTACK - use attack animation frames with better sync
                const numAttackFrames = charDataClient.num_attack;
                const elapsedAttackTime = SERVER_ATTACK_DURATION - player.attack_timer; 
                const timePerFrame = SERVER_ATTACK_DURATION / numAttackFrames;
                frameIndex = Math.min(numAttackFrames - 1, Math.max(0, Math.floor(elapsedAttackTime / timePerFrame)));
                currentImageKey = `char_${charKey}_attack_${frameIndex}`;
            }
        } else if (player.is_jumping) {
            currentImageKey = `char_${charKey}_jump`;
        } else if (player.is_ducking) {
            currentImageKey = `char_${charKey}_duck`;
        } else if (player.current_animation === 'walk') {
            const numWalkFrames = charDataClient.num_walk;
            if (Date.now() - animState.walk_timer > WALK_ANIMATION_MS_PER_FRAME) {
                animState.walk_frame = (animState.walk_frame + 1) % numWalkFrames;
                animState.walk_timer = Date.now();
            }
            frameIndex = animState.walk_frame;
            currentImageKey = `char_${charKey}_walk_${frameIndex}`;
        } else { 
            currentImageKey = `char_${charKey}_idle`; 
        }

        const currentImage = loadedAssets.images[currentImageKey] || loadedAssets.images[`char_${charKey}_idle`];

        if (currentImage) {
            const scaledWidth = currentImage.width * SPRITE_SCALE;
            const scaledHeight = currentImage.height * SPRITE_SCALE;
            // IMPROVED: Better sprite centering - sprites are centered on their bottom-middle
            const drawX = player.x - scaledWidth / 2;
            const drawY = player.y - scaledHeight; 

            if (player.facing === -1) {
                ctx.save(); 
                ctx.scale(-1, 1);
                ctx.drawImage(currentImage, -drawX - scaledWidth, drawY, scaledWidth, scaledHeight);
                ctx.restore();
            } else {
                ctx.drawImage(currentImage, drawX, drawY, scaledWidth, scaledHeight);
            }
        } else { 
            if(charKey && ASSET_PATHS.characters[charKey]) console.warn("Missing image for key:", currentImageKey); 
        }
    });
    
    // FIXED: Handle both quickening and dark quickening effects
    if (roomState.quickening_effect_active || roomState.dark_quickening_effect_active) {
        if (Math.floor(Date.now() / (QUICKENING_FLASH_DURATION_MS_CLIENT / 2)) % 2 === 0) { 
            // Full screen inversion
            ctx.save();
            ctx.globalCompositeOperation = 'difference';
            ctx.fillStyle = 'white'; 
            ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
            ctx.restore();
            
            // Show the appropriate effect image
            const effectImgKey = roomState.dark_quickening_effect_active ? 'ui_darkQuickening' : 'ui_quickening';
            const effectImg = loadedAssets.images[effectImgKey];
            if (effectImg) {
                ctx.save();
                ctx.globalAlpha = 0.7; // Make overlay partially transparent
                ctx.drawImage(effectImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
                ctx.restore();
            }
        }
    }
    
    // NEW: Handle clash flash effect for dramatic knockback
    if (roomState.clash_flash_timer > 0) {
        ctx.save();
        ctx.fillStyle = 'white';
        ctx.globalAlpha = 0.3 * (roomState.clash_flash_timer / 5); // Fade out effect
        ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
        ctx.restore();
    }
}

// FIXED: Church victory handling - match original kylander2.py behavior exactly
function drawRoundVictoryScreen() {
    let bgKey = `bg_victory_${roomState.current_background_index || 0}`;
    
    // FIXED: Special church victory screen handling using UI assets
    if (roomState.current_background_key === 'church_victory') {
        // Use UI assets for church victory screens
        bgKey = `ui_churchVictory${roomState.current_background_index === 1 ? '2' : '1'}`;
        console.log(`Church victory screen using UI asset: ${bgKey}`);
    }
    
    const bgImg = loadedAssets.images[bgKey];
    if (bgImg) {
        ctx.drawImage(bgImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    } else {
        console.warn(`Church victory background not found: ${bgKey}`);
        ctx.fillStyle = 'darkblue'; 
        ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
    }

    let winnerDisplayName = "Winner";
    if (roomState.round_winner_player_id && roomState.players) {
        const p = Object.values(roomState.players).find(pl => pl.id === roomState.round_winner_player_id);
        winnerDisplayName = p?.display_character_name || p?.character_name || roomState.round_winner_player_id;
    } else if (roomState.round_winner_player_id) { 
        winnerDisplayName = roomState.round_winner_player_id; 
    }
    
    // FIXED: Only show victory text if this is NOT a church victory (no sound case)
    if (roomState.current_background_key !== 'church_victory') {
        ctx.font='50px HighlanderFont, Arial Black'; 
        ctx.fillStyle='white'; 
        ctx.textAlign='center'; 
        ctx.strokeStyle='black'; 
        ctx.lineWidth=4;
        ctx.shadowColor = "rgba(0,0,0,0.8)"; 
        ctx.shadowBlur = 10; 
        ctx.shadowOffsetX = 3; 
        ctx.shadowOffsetY = 3;
        ctx.strokeText(`${winnerDisplayName} WINS ROUND!`, GAME_WIDTH/2, GAME_HEIGHT/3);
        ctx.fillText(`${winnerDisplayName} WINS ROUND!`, GAME_WIDTH/2, GAME_HEIGHT/3);
        ctx.font='30px HighlanderFont, Arial Black';
        ctx.strokeText("THERE CAN BE ONLY ONE", GAME_WIDTH/2, GAME_HEIGHT - 80);
        ctx.fillText("THERE CAN BE ONLY ONE", GAME_WIDTH/2, GAME_HEIGHT - 80);
        ctx.shadowBlur = 0; 
        ctx.shadowOffsetX = 0; 
        ctx.shadowOffsetY = 0; 
        ctx.textAlign='left';
    }
}

function drawFinalVictoryScreen() {
    const bgKey = `bg_victory_${roomState.current_background_index || 9}`;
    const bgImg = loadedAssets.images[bgKey] || loadedAssets.images['bg_paris_0'];
    if (bgImg) ctx.drawImage(bgImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    else { ctx.fillStyle = 'gold'; ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT); }

    let gameWinnerDisplayName = "CHAMPION";
    if (roomState.game_winner_player_id && roomState.players) {
        const p = Object.values(roomState.players).find(pl => pl.id === roomState.game_winner_player_id);
        gameWinnerDisplayName = p?.display_character_name || p?.character_name || roomState.game_winner_player_id;
    } else if (roomState.game_winner_player_id) { gameWinnerDisplayName = roomState.game_winner_player_id; }

    ctx.font = '60px HighlanderFont, Arial Black'; 
    ctx.fillStyle = 'white'; ctx.textAlign = 'center'; ctx.strokeStyle = 'black'; ctx.lineWidth = 5;
    ctx.shadowColor = "rgba(0,0,0,0.9)"; ctx.shadowBlur = 15; ctx.shadowOffsetX = 4; ctx.shadowOffsetY = 4;
    ctx.strokeText(`${gameWinnerDisplayName}`, GAME_WIDTH / 2, GAME_HEIGHT / 3 - 20);
    ctx.fillText(`${gameWinnerDisplayName}`, GAME_WIDTH / 2, GAME_HEIGHT / 3 - 20);
    ctx.font = '40px HighlanderFont, Arial Black';
    ctx.strokeText("HAS WON THE PRIZE!", GAME_WIDTH / 2, GAME_HEIGHT / 3 + 50);
    ctx.fillText("HAS WON THE PRIZE!", GAME_WIDTH / 2, GAME_HEIGHT / 3 + 50);
    ctx.font = '30px HighlanderFont, Arial Black';
    ctx.strokeText("THERE CAN BE ONLY ONE", GAME_WIDTH / 2, GAME_HEIGHT - 80);
    ctx.fillText("THERE CAN BE ONLY ONE", GAME_WIDTH / 2, GAME_HEIGHT - 80);
    ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; ctx.textAlign = 'left';
}

function drawGameOverScreen() {
    const gameOverImg = loadedAssets.images['ui_gameOver'];
    if (gameOverImg) ctx.drawImage(gameOverImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    else {
        ctx.fillStyle = 'black';
        ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
        ctx.font = '60px HighlanderFont, Arial Black'; 
        ctx.fillStyle = 'red'; ctx.textAlign = 'center'; ctx.strokeStyle = 'black'; ctx.lineWidth = 5;
        ctx.shadowColor = "rgba(0,0,0,0.9)"; ctx.shadowBlur = 15; ctx.shadowOffsetX = 4; ctx.shadowOffsetY = 4;
        ctx.strokeText("GAME OVER", GAME_WIDTH / 2, GAME_HEIGHT / 2);
        ctx.fillText("GAME OVER", GAME_WIDTH / 2, GAME_HEIGHT / 2);
        ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; ctx.textAlign = 'left';
    }
}

function drawChurchIntroScreen() {
    const introImg = loadedAssets.images['ui_churchIntro'];
    if (introImg) ctx.drawImage(introImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    else {
        ctx.fillStyle = 'darkred'; ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
        ctx.fillStyle = 'white'; ctx.font = '30px HighlanderFont, Arial Black'; ctx.textAlign = 'center';
        ctx.fillText("HOLY GROUND", GAME_WIDTH / 2, GAME_HEIGHT / 2);
        ctx.textAlign = 'left';
    }
}

// COMBINED: Church victory screen with corrected background logic AND Darichris text overlay
function drawChurchVictoryScreen() {
    // FIXED: Correct background key construction - index 0 = churchvictory.png, index 1 = churchvictory2.png
    const bgIndex = roomState.current_background_index || 0;
    const bgKey = `ui_churchVictory${bgIndex === 0 ? '1' : '2'}`;  // FIXED: 0 = churchVictory1, 1 = churchVictory2
    const bgImg = loadedAssets.images[bgKey];
    
    console.log(`Church victory: bgIndex=${bgIndex}, bgKey=${bgKey}, bgImg found=${!!bgImg}`);
    
    if (bgImg) {
        ctx.drawImage(bgImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    } else {
        console.warn(`Church victory background not found: ${bgKey}`);
        ctx.fillStyle = 'darkblue'; 
        ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
        ctx.fillStyle = 'white'; 
        ctx.font = '40px HighlanderFont, Arial Black'; 
        ctx.textAlign = 'center';
        ctx.fillText("CHURCH VICTORY", GAME_WIDTH / 2, GAME_HEIGHT / 2);
        ctx.textAlign = 'left';
    }

    // KEPT: Darichris text overlay from game (1).js
    if (roomState.church_victory_sound_triggered) {
        const bgIndex = roomState.church_victory_bg_index || roomState.current_background_index || 0;
        const message = bgIndex === 0 ? "DARICHRIS OFFERS COUNCIL" : "DARICHRIS SHARES HIS MEAD";
        
        ctx.font = '28px HighlanderFont, Arial Black';
        ctx.fillStyle = 'white';
        ctx.textAlign = 'center';
        ctx.strokeStyle = 'black';
        ctx.lineWidth = 3;
        ctx.shadowColor = "rgba(0,0,0,0.9)";
        ctx.shadowBlur = 6;
        ctx.shadowOffsetX = 3;
        ctx.shadowOffsetY = 3;
        ctx.strokeText(message, GAME_WIDTH / 2, GAME_HEIGHT - 60);
        ctx.fillText(message, GAME_WIDTH / 2, GAME_HEIGHT - 60);
        ctx.shadowBlur = 0;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 0;
        ctx.textAlign = 'left';
    }
}

// FIXED: Add special end screen with dark quickening only
function drawSpecialEndScreen() {
    // Show current background
    const bgCategory = roomState.special_level_active ? 'church' : (roomState.current_background_key || 'paris');
    const bgIndex = roomState.current_background_index || 0;
    const bgKey = `bg_${bgCategory}_${bgIndex}`;
    const bgImg = loadedAssets.images[bgKey] || loadedAssets.images['bg_paris_0'];
    if (bgImg) ctx.drawImage(bgImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
    
    // Draw players
    drawTopPlayerUI(Object.values(roomState.players || {}).find(p => p.id === 'player1'), 30, 30);
    drawTopPlayerUI(Object.values(roomState.players || {}).find(p => p.id === 'player2'), GAME_WIDTH - 200 - 30, 30, true);
    
    // Draw fighters (same as playing screen)
    const fightersToDraw = [];
    if (roomState.players) {
        Object.values(roomState.players).forEach(p_state => {
            if (p_state.character_name && ASSET_PATHS.characters[p_state.character_name]) {
                 fightersToDraw.push(p_state);
            }
        });
    }
    fightersToDraw.sort((a, b) => a.y - b.y);

    fightersToDraw.forEach(player => {
        const charKey = player.character_name; 
        const charDataClient = ASSET_PATHS.characters[charKey];
        if (!charDataClient) { return; } 

        const currentImageKey = `char_${charKey}_idle`;
        const currentImage = loadedAssets.images[currentImageKey];

        if (currentImage) {
            const scaledWidth = currentImage.width * SPRITE_SCALE;
            const scaledHeight = currentImage.height * SPRITE_SCALE;
            const drawX = player.x - scaledWidth / 2;
            const drawY = player.y - scaledHeight; 

            if (player.facing === -1) {
                ctx.save(); 
                ctx.scale(-1, 1);
                ctx.drawImage(currentImage, -drawX - scaledWidth, drawY, scaledWidth, scaledHeight);
                ctx.restore();
            } else {
                ctx.drawImage(currentImage, drawX, drawY, scaledWidth, scaledHeight);
            }
        }
    });
    
    // FIXED: Show dark quickening effect for SPECIAL_END
    if (roomState.dark_quickening_effect_active) {
        if (Math.floor(Date.now() / (QUICKENING_FLASH_DURATION_MS_CLIENT / 2)) % 2 === 0) { 
            // Full screen inversion
            ctx.save();
            ctx.globalCompositeOperation = 'difference';
            ctx.fillStyle = 'white'; 
            ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
            ctx.restore();
            
            // Show dark quickening image
            const darkQuickImg = loadedAssets.images['ui_darkQuickening'];
            if (darkQuickImg) {
                ctx.save();
                ctx.globalAlpha = 0.8; // Make overlay more visible
                ctx.drawImage(darkQuickImg, 0, 0, GAME_WIDTH, GAME_HEIGHT);
                ctx.restore();
            }
        }
    }
}

function drawSlideshowScreen() {
    ctx.fillStyle = 'black'; ctx.fillRect(0,0,GAME_WIDTH,GAME_HEIGHT);
    const bgKey = `bg_slideshow_${roomState.current_background_index || 0}`;
    const bgImg = loadedAssets.images[bgKey];
    if(bgImg) ctx.drawImage(bgImg, 0,0,GAME_WIDTH, GAME_HEIGHT);
    else { ctx.font='30px HighlanderFont, Arial'; ctx.textAlign='center'; ctx.fillText("SLIDESHOW", GAME_WIDTH/2, GAME_HEIGHT/2);}
    ctx.font='20px HighlanderFont, Arial Black'; 
    ctx.fillStyle='white'; ctx.textAlign='center'; ctx.strokeStyle='black'; ctx.lineWidth=2;
    ctx.shadowColor = "rgba(0,0,0,0.7)"; ctx.shadowBlur = 5; ctx.shadowOffsetX = 1; ctx.shadowOffsetY = 1;
    ctx.strokeText("Press ENTER to return to Title", GAME_WIDTH/2, GAME_HEIGHT-50);
    ctx.fillText("Press ENTER to return to Title", GAME_WIDTH/2, GAME_HEIGHT-50);
    ctx.shadowBlur = 0; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0; ctx.textAlign='left';
}

function cleanupAnimationStates() {
    Object.keys(clientPlayerAnimationState).forEach(playerId => {
        if (clientPlayerAnimationState[playerId]) {
            clientPlayerAnimationState[playerId] = { walk_frame: 0, walk_timer: 0 };
        }
    });
}

let lastActionSendTime = 0;
const actionSendInterval = 1000 / 30; 

function gameLoop(currentTime) {
    ctx.clearRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1.0;
    
    if (!allAssetsLoaded || Object.keys(roomState).length === 0) {
        drawLoadingScreen();
    } else {
        switch (roomState.current_screen) {
            case 'TITLE': 
                cleanupAnimationStates();
                drawTitleScreen(); 
                break;
            case 'MODE_SELECT': 
                cleanupAnimationStates();
                drawModeSelectScreen(); 
                break;
            case 'CHARACTER_SELECT_P1': 
            case 'CHARACTER_SELECT_P2': 
                cleanupAnimationStates();
                drawCharacterSelectScreen(); 
                break;
            case 'CONTROLS': 
                cleanupAnimationStates();
                drawControlsScreen(); 
                break; 
            case 'CHURCH_INTRO': 
                cleanupAnimationStates();
                drawChurchIntroScreen(); 
                break;
            case 'PLAYING': 
            case 'SPECIAL':
                drawPlayingScreen();
                if (currentTime - lastActionSendTime > actionSendInterval) {
                    sendPlayerActions(); 
                    lastActionSendTime = currentTime;
                }
                break;
            // FIXED: Add separate handling for SPECIAL_END
            case 'SPECIAL_END':
                drawSpecialEndScreen();
                break;
            case 'VICTORY': 
                cleanupAnimationStates();
                drawRoundVictoryScreen(); 
                break; 
            // FIXED: Add CHURCH_VICTORY state
            case 'CHURCH_VICTORY':
            case 'CHURCH_VICTORY_IMMEDIATE':
                cleanupAnimationStates();
                drawChurchVictoryScreen();
                break;
            case 'FINAL': 
                cleanupAnimationStates();
                drawFinalVictoryScreen(); 
                break;   
            case 'GAME_OVER': 
                cleanupAnimationStates();
                drawGameOverScreen(); 
                break;
            case 'SLIDESHOW': 
                cleanupAnimationStates();
                drawSlideshowScreen(); 
                break;
            default: 
                cleanupAnimationStates();
                ctx.fillStyle = 'purple'; 
                ctx.fillRect(0, 0, GAME_WIDTH, GAME_HEIGHT);
                ctx.fillStyle = 'white'; 
                ctx.textAlign = 'center';
                ctx.font='20px HighlanderFont, Arial';
                ctx.fillText(`State: ${roomState.current_screen || 'Unknown...'}`, GAME_WIDTH / 2, GAME_HEIGHT / 2);
                ctx.textAlign = 'left'; 
                break;
        }
    }
    
    if (requestAnimationFrameId) {
        cancelAnimationFrame(requestAnimationFrameId);
    }
    requestAnimationFrameId = requestAnimationFrame(gameLoop);
}

socket.on('connect', () => { console.log('Connected:', socket.id); });
socket.on('assign_player_id', (data) => {
    localPlayerId = data.playerId; 
    roomState = data.initialRoomState;
    console.log('Assigned ID:', localPlayerId, 'Initial State Received. Screen:', roomState.current_screen);
});

// ENHANCED: Slideshow music handling with Darius sound support
socket.on('update_room_state', (newRoomState) => {
    const oldScreen = roomState.current_screen;
    const oldRoundWinner = roomState.round_winner_player_id;
    const oldSlideshowMusic = roomState.slideshow_music_started;
    const oldSlideshow = (roomState.current_screen === 'SLIDESHOW');
    const oldChurchVictorySound = roomState.church_victory_sound_triggered; // NEW: Track church victory sound
    roomState = newRoomState;

    if (roomState.round_winner_player_id && roomState.round_winner_player_id !== oldRoundWinner) {
        roundVictorySfxPlayed = false; 
    }
    
    if ((oldScreen === 'VICTORY' || oldScreen === 'FINAL' || oldScreen === 'CHURCH_VICTORY' || oldScreen === 'CHURCH_VICTORY_IMMEDIATE') && 
        (roomState.current_screen !== 'VICTORY' && roomState.current_screen !== 'FINAL' && roomState.current_screen !== 'CHURCH_VICTORY' && roomState.current_screen !== 'CHURCH_VICTORY_IMMEDIATE')) {
        roundVictorySfxPlayed = false;
    }

    // ENHANCED: Better music handling with explicit slideshow music stopping
    if (oldScreen !== roomState.current_screen) {
        console.log(`Client: Screen changed from ${oldScreen} to ${roomState.current_screen}`);
        console.log(`Old slideshow music: ${oldSlideshowMusic}, New slideshow music: ${roomState.slideshow_music_started}`);
        
        // Start main music if we're entering a gameplay screen and it's not playing
        if (!musicInitialized && ['TITLE', 'MODE_SELECT', 'CHARACTER_SELECT_P1', 'CHARACTER_SELECT_P2', 'CONTROLS', 'CHURCH_INTRO', 'PLAYING', 'SPECIAL', 'SPECIAL_END'].includes(roomState.current_screen)) {
            console.log("Initializing main music");
            playMusic('music_backgroundMusic');
        }
        // Switch to slideshow music when entering slideshow
        else if (roomState.current_screen === 'SLIDESHOW' && roomState.slideshow_music_started) {
            console.log("Starting slideshow music");
            playMusic('music_slideshowMusic');
        }
        // CRITICAL FIX: Handle slideshow music stopping more reliably
        else if (roomState.current_screen === 'TITLE' && oldSlideshow) {
            console.log("CRITICAL: Slideshow to Title transition - forcing main music restart");
            
            // Force stop ALL music
            if (currentMusic) {
                console.log("Stopping current music:", currentMusic.src);
                currentMusic.pause();
                currentMusic.currentTime = 0;
                currentMusic = null;
            }
            
            // Reset all music states
            mainMusicPlaying = false;
            musicInitialized = false;
            
            // Force restart main music with delay
            setTimeout(() => {
                console.log("Restarting main music after slideshow");
                playMusic('music_backgroundMusic');
            }, 100);
        }
        else if (roomState.current_screen === 'TITLE' && (!roomState.slideshow_music_started && oldSlideshowMusic)) {
            console.log("Slideshow music stopped signal received");
            
            // Force stop current music
            if (currentMusic) {
                console.log("Stopping slideshow music");
                currentMusic.pause();
                currentMusic.currentTime = 0;
                currentMusic = null;
            }
            
            // Reset and restart main music
            mainMusicPlaying = false;
            musicInitialized = false;
            
            setTimeout(() => {
                console.log("Starting main music after stop signal");
                playMusic('music_backgroundMusic');
            }, 100);
        }
        // Stop music only at the very end of the game during final victory/game over
        else if (['FINAL', 'GAME_OVER'].includes(roomState.current_screen)) {
            stopMusic();
        }

        // Rest of victory sound handling remains the same...
        if (roomState.current_screen === 'CHURCH_VICTORY' || roomState.current_screen === 'CHURCH_VICTORY_IMMEDIATE') {
            roundVictorySfxPlayed = true;
        }
        else if (roomState.current_screen === 'VICTORY' && roomState.round_winner_player_id && !roundVictorySfxPlayed) {
            const sfxKeys = ['sfx_victoryKurgan', 'sfx_victoryBurnOut', 'sfx_victoryGoat', 'sfx_victoryDuncan', 'sfx_victoryKalas'];
            let sfxToPlayKey = null;
            if (roomState.victory_sfx_to_play_index !== undefined && roomState.victory_sfx_to_play_index >= 0 && roomState.victory_sfx_to_play_index < sfxKeys.length) {
                sfxToPlayKey = sfxKeys[roomState.victory_sfx_to_play_index];
            } else { 
                sfxToPlayKey = sfxKeys[Math.floor(Math.random() * sfxKeys.length)];
            }
            if(loadedAssets.sounds[sfxToPlayKey]) {
                loadedAssets.sounds[sfxToPlayKey].currentTime = 0; 
                loadedAssets.sounds[sfxToPlayKey].play().catch(e=>console.warn("SFX: victory error",e));
                roundVictorySfxPlayed = true;
            }
        }
        else if(roomState.current_screen === 'FINAL' && roomState.final_sound_played && loadedAssets.sounds['sfx_finalVictory'] && !(loadedAssets.sounds['sfx_finalVictory']._playedOnceFS)){
            loadedAssets.sounds['sfx_finalVictory'].play().catch(e=>console.warn("SFX: finalVictory error",e));
            loadedAssets.sounds['sfx_finalVictory']._playedOnceFS = true; 
        }
    }
    
    // ADDITIONAL CHECK: Handle slideshow music flag changes without screen changes
    if (oldScreen === roomState.current_screen && roomState.current_screen === 'SLIDESHOW' && oldSlideshowMusic && !roomState.slideshow_music_started) {
        console.log("Slideshow music flag changed to false - stopping music");
        if (currentMusic) {
            currentMusic.pause();
            currentMusic.currentTime = 0;
            currentMusic = null;
        }
        mainMusicPlaying = false;
        musicInitialized = false;
        
        setTimeout(() => {
            console.log("Starting main music after flag change");
            playMusic('music_backgroundMusic');
        }, 100);
    }
    
    if (roomState.current_screen !== 'FINAL' && loadedAssets.sounds['sfx_finalVictory']) {
        loadedAssets.sounds['sfx_finalVictory']._playedOnceFS = false;
    }

    // Enhanced sound effect management with Darius sound support
    if (roomState.sfx_event_for_client) {
        const sfx = loadedAssets.sounds[roomState.sfx_event_for_client];
        if (sfx) {
            sfx.currentTime = 0;
            sfx.play().catch(e => console.warn("SFX play error (event):", e));
        }
        
        if (roomState.sfx_event_for_client === 'sfx_swordEffects') {
            sfx.volume = 0.7;
        }
    }

    // NEW: Handle Darius sounds for church victory screens based on background
    if (roomState.church_victory_sound_triggered && !oldChurchVictorySound && 
        (roomState.current_screen === 'CHURCH_VICTORY' || roomState.current_screen === 'CHURCH_VICTORY_IMMEDIATE')) {
        
        // Determine which Darius sound to play based on church victory background index
        const bgIndex = roomState.church_victory_bg_index || roomState.current_background_index || 0;
        const soundKey = bgIndex === 0 ? 'sfx_darius2' : 'sfx_darius1'; // 0 = churchvictory.png (Darius2), 1 = churchvictory2.png (Darius1)
        const soundName = bgIndex === 0 ? 'Darius2' : 'Darius1';
        const bgName = bgIndex === 0 ? 'churchvictory.png' : 'churchvictory2.png';
        
        console.log(`Playing ${soundName} sound for church victory with ${bgName} (index ${bgIndex})`);
        
        const dariusSound = loadedAssets.sounds[soundKey];
        if (dariusSound) {
            dariusSound.currentTime = 0;
            dariusSound.volume = 0.8; // Slightly louder for dramatic effect
            dariusSound.play().catch(e => console.warn(`${soundName} sound play error:`, e));
        } else {
            console.warn(`${soundName} sound not loaded (key: ${soundKey})`);
        }
    }
});

socket.on('room_full', () => { 
    cleanupAnimationStates();
    if(requestAnimationFrameId) {
        cancelAnimationFrame(requestAnimationFrameId);
        requestAnimationFrameId = null;
    }
});

const keysPressed = {};

function handleKeyDown(e) {
    const key = e.key.toLowerCase();
    const gameControlKeys = [' ', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'q', 'e', 'a', 's', 'd', 'w', 'shift', 'alt', 'control', 'enter', 'b'];
    if (gameControlKeys.includes(key) || (key >= '1' && key <= '3')) e.preventDefault();
    if (!allAssetsLoaded) return;
    keysPressed[key] = true;

    if (roomState.current_screen === 'TITLE' && key === 'enter') {
        socket.emit('change_game_state', { newState: 'MODE_SELECT' });
    } else if (roomState.current_screen === 'MODE_SELECT') {
        if (key === '1') socket.emit('change_game_state', { newState: 'CHARACTER_SELECT_P1', mode: 'ONE' });
        else if (key === '2') socket.emit('change_game_state', { newState: 'CHARACTER_SELECT_P1', mode: 'TWO' });
    } else if (['CHARACTER_SELECT_P1', 'CHARACTER_SELECT_P2'].includes(roomState.current_screen)) {
        const charKeys = Object.keys(ASSET_PATHS.characters); 
        if (key >= '1' && key <= String(charKeys.length)) {
            socket.emit('player_character_choice', { characterName: charKeys[parseInt(key) - 1] });
        }
    } else if (roomState.current_screen === 'SLIDESHOW' && key === 'enter') {
        // IMPROVED: Stop slideshow music when manually returning to title
        console.log("Enter pressed during slideshow - stopping slideshow music");
        socket.emit('change_game_state', { newState: 'TITLE_SCREEN' });
    } else if (['PLAYING', 'SPECIAL'].includes(roomState.current_screen) && key === 'b') {
        // FIXED: Allow background change during both normal and special gameplay
        console.log("B key pressed - changing background. Current screen:", roomState.current_screen);
        console.log("Current background:", roomState.current_background_key, roomState.current_background_index);
        console.log("Special level active:", roomState.special_level_active);
        e.preventDefault(); // Make sure event is prevented
        socket.emit('change_background', { /* empty data object */ });
    }
}

function handleKeyUp(e) { 
    const key = e.key.toLowerCase();
    delete keysPressed[key]; 
    if (allAssetsLoaded && ['PLAYING', 'SPECIAL'].includes(roomState.current_screen) && localPlayerId && roomState.players) {
        const myClientPlayerObject = Object.values(roomState.players).find(p => p.sid === socket.id);
        if (myClientPlayerObject) {
            let pControlsDuckKey = 's'; // Default P1 duck
            if (myClientPlayerObject.id === 'player1' && roomState.game_mode === 'ONE') {
                pControlsDuckKey = 'arrowdown';
            } else if (myClientPlayerObject.id === 'player2') {
                pControlsDuckKey = 'arrowdown';
            }
            if (key === pControlsDuckKey && myClientPlayerObject.is_ducking) { 
                socket.emit('player_actions', { actions: [{ type: 'duck', active: false }] });
            }
        }
    }
}

window.addEventListener('keydown', handleKeyDown);
window.addEventListener('keyup', handleKeyUp);


function sendPlayerActions() {
    if (!['PLAYING', 'SPECIAL'].includes(roomState.current_screen) || !localPlayerId || !roomState.players || !socket.connected) return;
    const myClientPlayerObject = Object.values(roomState.players).find(p => p.sid === socket.id);
    if (!myClientPlayerObject || myClientPlayerObject.health <= 0) return;

    const actions = [];
    let pControls;
    if (myClientPlayerObject.id === 'player1') {
        if (roomState.game_mode === 'ONE') {
            pControls = { left: 'arrowleft', right: 'arrowright', jump: 'arrowup', duck: 'arrowdown', attack: [' '] };
        } else { 
            pControls = { left: 'a', right: 'd', jump: 'w', duck: 's', attack: ['q', 'e'] };
        }
    } else { 
        pControls = { left: 'arrowleft', right: 'arrowright', jump: 'arrowup', duck: 'arrowdown', attack: ['enter'] };
    }

    if (keysPressed[pControls.left]) actions.push({ type: 'move', direction: 'left' });
    if (keysPressed[pControls.right]) actions.push({ type: 'move', direction: 'right' });
    if (keysPressed[pControls.jump]) actions.push({ type: 'jump' }); 
    
    let currentDuckStateClient = keysPressed[pControls.duck] || false;
    if (currentDuckStateClient && !myClientPlayerObject.is_ducking) actions.push({ type: 'duck', active: true });
    
    let attackKeyDown = pControls.attack.some(key => keysPressed[key]);
    if (attackKeyDown && !myClientPlayerObject.is_attacking && myClientPlayerObject.cooldown_timer === 0) {
        actions.push({ type: 'attack' });
        // Let server handle all attack sounds for consistency
    }
    
    // FIXED: Always send actions to server, even if empty
    // This allows server to detect when movement keys are released
    socket.emit('player_actions', { actions: actions });
}

function enableAudioContext() {
    console.log("User interaction detected, attempting to enable audio context.");
    let audioContextResumed = false;
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
        const tempCtx = new AudioContext();
        if (tempCtx.state === 'suspended') {
            tempCtx.resume().then(() => {
                console.log("AudioContext resumed via dummy context.");
                audioContextResumed = true;
                if (currentMusic && currentMusic.paused) {
                    currentMusic.play().catch(e => console.warn("Error playing music post-interaction (ctx resume):", e));
                } else if (mainMusicPlaying && !currentMusic && loadedAssets.sounds['music_backgroundMusic']){
                    playMusic('music_backgroundMusic');
                }
            }).catch(e => console.warn("Dummy AudioContext resume error:", e));
        } else { audioContextResumed = true; }
    }

    if (!audioContextResumed && Object.values(loadedAssets.sounds).length > 0) {
        const firstSound = Object.values(loadedAssets.sounds)[0];
        if (firstSound && typeof firstSound.play === 'function' && firstSound.paused) {
             const playPromise = firstSound.play();
             if (playPromise !== undefined) {
                 playPromise.then(() => {
                     firstSound.pause();
                     if(firstSound !== currentMusic) firstSound.currentTime = 0;
                     console.log("Audio context likely unlocked by playing and pausing a sound.");
                     audioContextResumed = true;
                 }).catch((error) => { console.warn("Audio context unlock (direct sound play) was prevented:", error); });
             }
        }
    }
    if (audioContextResumed && mainMusicPlaying && currentMusic && currentMusic.paused) {
        currentMusic.play().catch(e => console.warn("Error playing music post-interaction (final attempt):", e));
    } else if (audioContextResumed && mainMusicPlaying && !currentMusic && loadedAssets.sounds['music_backgroundMusic']){
        playMusic('music_backgroundMusic');
    }
}
window.addEventListener('click', enableAudioContext, { once: true });
window.addEventListener('keydown', enableAudioContext, { once: true });

loadAllAssets().then(() => {
    console.log("Asset loading phase complete.");
    function animationLoop(time) { gameLoop(time); requestAnimationFrameId = requestAnimationFrame(animationLoop); }
    requestAnimationFrameId = requestAnimationFrame(animationLoop);
}).catch(err => { 
    console.error("Error during initial asset loading promise:", err);
    ctx.fillStyle = 'black'; ctx.fillRect(0,0, GAME_WIDTH, GAME_HEIGHT);
    ctx.fillStyle = 'red'; ctx.font = '20px HighlanderFont, Arial'; ctx.textAlign = 'center';
    ctx.fillText("Error loading assets. Please check console.", GAME_WIDTH / 2, 50);
    ctx.textAlign = 'left';
});
