"""
Super Mario Bros. - 2D Side-Scrolling Platformer in Python
===========================================================
A complete, structured, and modular platformer built with Pygame / Pygame-CE.

Key Architecture & Mechanics:
  1. Engine & Game Loop:
     - Fixed 60 FPS tick rate, event pump, state machine (PLAYING, DYING, STAGE_CLEAR, GAME_OVER, PAUSED).
  2. Physics & Player Controller:
     - Sub-pixel floating-point position tracking.
     - Smooth acceleration, max running dash, ground friction, and skidding mechanics.
     - Variable jump height (attenuating upward impulse if jump button is released early).
     - Coyote Time (6 frames grace period after walking off a ledge).
     - Jump Buffering (6 frames grace period for pressing jump before landing).
  3. Collision System:
     - Separated X and Y axis collision detection against solid tiles.
     - Eliminates corner snagging and phase-through bugs.
     - Interactive block bumps: Question blocks [?] bounce up, dispense a coin, and turn into empty blocks.
  4. Enemy AI (Goomba):
     - Autonomous horizontal patrol.
     - Wall collision reversal and ledge navigation.
     - Stomp detection: landing on top squashes the Goomba and bounces Mario upward; side collision hurts Mario.
  5. Camera System:
     - Side-scrolling viewport with smooth deadzone tracking and level boundary clamping.
     - Parallax background scrolling (clouds and distant rolling hills).
  6. Asset & Audio Management:
     - Built-in procedural 8-bit NES pixel art generator (100% self-contained; zero missing-file errors!).
     - Automatic external asset loader hook: drops in PNG spritesheets from an `assets/` folder if present.
     - Synthesized 8-bit retro sound engine (jump, coin, stomp, bump, fanfare, death) using raw PCM square waves.

Controls:
  Left / Right (or A / D) : Move Left / Right
  Space / Up / Z / W      : Jump (Hold for high jump, tap for short hop)
  Left Shift / X          : Run / Dash
  P                       : Pause / Resume
  R                       : Restart / Respawn
  ESC                     : Quit
"""

from __future__ import annotations

import math
import os
import struct
import sys
from typing import Dict, List, Optional, Tuple

import pygame

# ==============================================================================
# 1. GAME CONSTANTS & CONFIGURATION
# ==============================================================================
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
TILE_SIZE = 32
FPS = 60

# Palette (NES Super Mario Bros. Authentic Colors)
COLOR_SKY = (92, 148, 252)
COLOR_GROUND_ORANGE = (228, 92, 16)
COLOR_GROUND_DARK = (156, 74, 0)
COLOR_BRICK_RED = (184, 68, 24)
COLOR_BRICK_DARK = (107, 36, 12)
COLOR_QUESTION_GOLD = (252, 160, 48)
COLOR_QUESTION_DARK = (180, 100, 20)
COLOR_EMPTY_BLOCK = (140, 90, 60)
COLOR_PIPE_GREEN = (0, 168, 0)
COLOR_PIPE_DARK = (0, 104, 0)
COLOR_PIPE_LIGHT = (80, 208, 32)
COLOR_MARIO_RED = (216, 40, 0)
COLOR_MARIO_BLUE = (0, 72, 224)
COLOR_MARIO_SKIN = (252, 152, 56)
COLOR_MARIO_BROWN = (136, 80, 0)
COLOR_GOOMBA_BROWN = (168, 64, 0)
COLOR_GOOMBA_SKIN = (248, 176, 96)
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_GOLD = (252, 216, 0)

# Movement & Physics Parameters
GRAVITY = 0.82
TERMINAL_VELOCITY = 13.0
WALK_ACCEL = 0.45
RUN_ACCEL = 0.75
FRICTION = 0.85
SKID_FRICTION = 0.68
MAX_WALK_SPEED = 3.6
MAX_RUN_SPEED = 6.2
JUMP_FORCE = -13.6
JUMP_CUT_MODIFIER = 0.48   # Cuts upward speed on early jump key release
COYOTE_TIME_FRAMES = 6     # Frames to allow jump after walking off a ledge
JUMP_BUFFER_FRAMES = 6     # Frames to remember jump press before touching ground
ENEMY_SPEED = 1.3


# ==============================================================================
# 2. AUDIO SYNTHESIS ENGINE (Authentic 8-Bit Retro Audio)
# ==============================================================================
class RetroSoundEngine:
    """Synthesizes retro 8-bit square-wave audio in real time with zero file dependencies."""

    def __init__(self) -> None:
        self.enabled = False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self.sample_rate = 22050
            self.sounds: Dict[str, pygame.mixer.Sound] = {}
            self._synthesize_sound_bank()
            self.enabled = True
        except Exception as exc:
            print(f"[RetroSoundEngine] Audio disabled: {exc}")

    def _make_square_wave(
        self,
        duration: float,
        start_freq: float,
        end_freq: float,
        volume: float = 0.32,
        duty: float = 0.5,
    ) -> pygame.mixer.Sound:
        num_samples = int(self.sample_rate * duration)
        buf = bytearray()
        amp = int(32767 * volume)

        for i in range(num_samples):
            fraction = i / max(1, num_samples - 1)
            current_freq = start_freq + (end_freq - start_freq) * fraction
            t = i / self.sample_rate
            phase = (t * current_freq) % 1.0
            val = amp if phase < duty else -amp
            if i > num_samples - 120:  # Smooth anti-pop fadeout
                fade = (num_samples - i) / 120.0
                val = int(val * fade)
            buf.extend(struct.pack("<h", val))

        return pygame.mixer.Sound(buffer=bytes(buf))

    def _synthesize_sound_bank(self) -> None:
        # Jump: Fast rising pitch sweep
        self.sounds["jump"] = self._make_square_wave(0.16, 250.0, 780.0, volume=0.25)

        # Coin: Classic B5 to E6 two-note chime
        coin_buf = bytearray()
        amp = int(32767 * 0.28)
        step = int(self.sample_rate * 0.08)
        for freq in [987.77, 1318.51]:
            for i in range(step):
                t = i / self.sample_rate
                phase = (t * freq) % 1.0
                val = amp if phase < 0.5 else -amp
                coin_buf.extend(struct.pack("<h", val))
        self.sounds["coin"] = pygame.mixer.Sound(buffer=bytes(coin_buf))

        # Stomp: Low crunch pop
        self.sounds["stomp"] = self._make_square_wave(0.12, 420.0, 80.0, volume=0.35)

        # Bump: Head bonk thud
        self.sounds["bump"] = self._make_square_wave(0.08, 160.0, 80.0, volume=0.30)

        # Die: Descending chromatic death motif
        die_buf = bytearray()
        amp_die = int(32767 * 0.28)
        die_freqs = [523, 493, 440, 392, 329, 261, 164]
        note_step = int(self.sample_rate * 0.09)
        for f in die_freqs:
            for i in range(note_step):
                t = i / self.sample_rate
                phase = (t * f) % 1.0
                val = amp_die if phase < 0.5 else -amp_die
                die_buf.extend(struct.pack("<h", val))
        self.sounds["die"] = pygame.mixer.Sound(buffer=bytes(die_buf))

        # Stage Clear: Victorious ascending fanfare
        clear_buf = bytearray()
        clear_freqs = [523.25, 659.25, 783.99, 1046.50]
        step_len = int(self.sample_rate * 0.13)
        for f in clear_freqs:
            for i in range(step_len):
                t = i / self.sample_rate
                phase = (t * f) % 1.0
                val = amp_die if phase < 0.5 else -amp_die
                clear_buf.extend(struct.pack("<h", val))
        self.sounds["clear"] = pygame.mixer.Sound(buffer=bytes(clear_buf))

    def play(self, sound_name: str) -> None:
        if self.enabled and sound_name in self.sounds:
            try:
                self.sounds[sound_name].play()
            except Exception:
                pass


# ==============================================================================
# 3. ASSET MANAGER & PROCEDURAL PIXEL ART GENERATOR
# ==============================================================================
class AssetManager:
    """Manages all game surfaces. Generates NES-accurate pixel art procedurally,

    with fallback support for loading custom spritesheet images if present.
    """

    def __init__(self, asset_dir: str = "assets") -> None:
        self.asset_dir = asset_dir
        self.sprites: Dict[str, pygame.Surface] = {}
        self._generate_procedural_pixel_art()
        self._try_load_custom_assets()

    def _make_tile(self, w: int = 16, h: int = 16) -> pygame.Surface:
        return pygame.Surface((w, h), pygame.SRCALPHA)

    def _finalize(self, surf16: pygame.Surface) -> pygame.Surface:
        """Scales 16x16 native pixel art up to 32x32 world size via nearest-neighbor."""
        return pygame.transform.scale(surf16, (TILE_SIZE, TILE_SIZE))

    def _generate_procedural_pixel_art(self) -> None:
        # --- 1. Ground Block ---
        ground = self._make_tile()
        ground.fill(COLOR_GROUND_ORANGE)
        for x in range(16):
            ground.set_at((x, 0), COLOR_WHITE)
            ground.set_at((x, 15), COLOR_GROUND_DARK)
        for y in range(16):
            ground.set_at((0, y), COLOR_WHITE)
            ground.set_at((15, y), COLOR_GROUND_DARK)
        for pt in [(4, 4), (11, 4), (7, 9), (3, 12), (12, 11)]:
            ground.set_at(pt, COLOR_GROUND_DARK)
        self.sprites["ground"] = self._finalize(ground)

        # --- 2. Brick Block ---
        brick = self._make_tile()
        brick.fill(COLOR_BRICK_RED)
        for y in [0, 4, 8, 12, 15]:
            for x in range(16):
                brick.set_at((x, y), COLOR_BLACK)
        for x in [0, 8]:
            for y in range(0, 4):
                brick.set_at((x, y), COLOR_BLACK)
            for y in range(8, 12):
                brick.set_at((x, y), COLOR_BLACK)
        for x in [4, 12]:
            for y in range(4, 8):
                brick.set_at((x, y), COLOR_BLACK)
            for y in range(12, 15):
                brick.set_at((x, y), COLOR_BLACK)
        self.sprites["brick"] = self._finalize(brick)

        # --- 3. Question Block ---
        qblock = self._make_tile()
        qblock.fill(COLOR_QUESTION_GOLD)
        for x in range(16):
            qblock.set_at((x, 0), COLOR_WHITE)
            qblock.set_at((x, 15), COLOR_QUESTION_DARK)
        for y in range(16):
            qblock.set_at((0, y), COLOR_WHITE)
            qblock.set_at((15, y), COLOR_QUESTION_DARK)
        q_pixels = [
            (6, 3), (7, 3), (8, 3), (9, 3),
            (5, 4), (10, 4),
            (9, 5), (10, 5),
            (8, 6), (9, 6),
            (7, 7), (8, 7),
            (7, 8), (8, 8),
            (7, 11), (8, 11), (7, 12), (8, 12),
        ]
        for pt in q_pixels:
            qblock.set_at(pt, COLOR_BLACK)
        for pt in [(2, 2), (13, 2), (2, 13), (13, 13)]:
            qblock.set_at(pt, COLOR_QUESTION_DARK)
        self.sprites["question"] = self._finalize(qblock)

        # --- 4. Empty Block ---
        empty = self._make_tile()
        empty.fill(COLOR_EMPTY_BLOCK)
        for x in range(16):
            empty.set_at((x, 0), (180, 130, 90))
            empty.set_at((x, 15), (70, 40, 20))
        for y in range(16):
            empty.set_at((0, y), (180, 130, 90))
            empty.set_at((15, y), (70, 40, 20))
        for pt in [(2, 2), (13, 2), (2, 13), (13, 13)]:
            empty.set_at(pt, COLOR_BLACK)
        self.sprites["empty_block"] = self._finalize(empty)

        # --- 5. Pipe Segments ---
        pipe_top_l = self._make_tile()
        pipe_top_l.fill(COLOR_PIPE_GREEN)
        pipe_top_l.fill(COLOR_PIPE_LIGHT, pygame.Rect(2, 0, 4, 16))
        pipe_top_l.fill(COLOR_BLACK, pygame.Rect(0, 0, 1, 16))
        pipe_top_l.fill(COLOR_BLACK, pygame.Rect(0, 0, 16, 2))
        pipe_top_l.fill(COLOR_BLACK, pygame.Rect(0, 14, 16, 2))
        self.sprites["pipe_top_left"] = self._finalize(pipe_top_l)

        pipe_top_r = self._make_tile()
        pipe_top_r.fill(COLOR_PIPE_GREEN)
        pipe_top_r.fill(COLOR_PIPE_DARK, pygame.Rect(8, 0, 7, 16))
        pipe_top_r.fill(COLOR_BLACK, pygame.Rect(15, 0, 1, 16))
        pipe_top_r.fill(COLOR_BLACK, pygame.Rect(0, 0, 16, 2))
        pipe_top_r.fill(COLOR_BLACK, pygame.Rect(0, 14, 16, 2))
        self.sprites["pipe_top_right"] = self._finalize(pipe_top_r)

        pipe_body_l = self._make_tile()
        pipe_body_l.fill(COLOR_PIPE_GREEN)
        pipe_body_l.fill(COLOR_PIPE_LIGHT, pygame.Rect(3, 0, 4, 16))
        pipe_body_l.fill(COLOR_BLACK, pygame.Rect(1, 0, 1, 16))
        self.sprites["pipe_body_left"] = self._finalize(pipe_body_l)

        pipe_body_r = self._make_tile()
        pipe_body_r.fill(COLOR_PIPE_GREEN)
        pipe_body_r.fill(COLOR_PIPE_DARK, pygame.Rect(8, 0, 6, 16))
        pipe_body_r.fill(COLOR_BLACK, pygame.Rect(14, 0, 1, 16))
        self.sprites["pipe_body_right"] = self._finalize(pipe_body_r)

        # --- 6. Animated Coin ---
        for frame, width in enumerate([10, 6, 2, 6]):
            csurf = pygame.Surface((16, 16), pygame.SRCALPHA)
            x_offset = (16 - width) // 2
            pygame.draw.ellipse(csurf, COLOR_GOLD, (x_offset, 2, width, 12))
            if width > 4:
                pygame.draw.ellipse(csurf, (255, 240, 120), (x_offset + 1, 3, width - 2, 10), 1)
            self.sprites[f"coin_{frame}"] = self._finalize(csurf)

        # --- 7. Goomba Sprites ---
        for frame in [0, 1]:
            gsurf = self._make_tile()
            pygame.draw.ellipse(gsurf, COLOR_GOOMBA_BROWN, (1, 1, 14, 10))
            gsurf.fill(COLOR_GOOMBA_SKIN, pygame.Rect(4, 9, 8, 4))
            gsurf.set_at((4, 6), COLOR_WHITE)
            gsurf.set_at((5, 6), COLOR_BLACK)
            gsurf.set_at((10, 6), COLOR_WHITE)
            gsurf.set_at((11, 6), COLOR_BLACK)
            gsurf.set_at((3, 5), COLOR_BLACK)
            gsurf.set_at((4, 5), COLOR_BLACK)
            gsurf.set_at((11, 5), COLOR_BLACK)
            gsurf.set_at((12, 5), COLOR_BLACK)
            if frame == 0:
                gsurf.fill(COLOR_BLACK, pygame.Rect(1, 13, 5, 3))
                gsurf.fill(COLOR_BLACK, pygame.Rect(10, 13, 4, 3))
            else:
                gsurf.fill(COLOR_BLACK, pygame.Rect(2, 13, 4, 3))
                gsurf.fill(COLOR_BLACK, pygame.Rect(10, 13, 5, 3))
            self.sprites[f"goomba_{frame}"] = self._finalize(gsurf)

        gflat = self._make_tile()
        pygame.draw.ellipse(gflat, COLOR_GOOMBA_BROWN, (1, 9, 14, 6))
        gflat.fill(COLOR_BLACK, pygame.Rect(3, 11, 3, 2))
        gflat.fill(COLOR_BLACK, pygame.Rect(10, 11, 3, 2))
        self.sprites["goomba_squashed"] = self._finalize(gflat)

        # --- 8. Mario Sprites ---
        self._build_mario_sprites()

        # --- 9. Goal Elements ---
        pole = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        pygame.draw.rect(pole, (220, 220, 220), (14, 0, 4, 32))
        self.sprites["flagpole"] = pole

        finial = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        pygame.draw.circle(finial, COLOR_GOLD, (16, 20), 8)
        pygame.draw.rect(finial, (220, 220, 220), (14, 20, 4, 12))
        self.sprites["pole_top"] = finial

        flag = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
        pygame.draw.polygon(flag, (0, 200, 0), [(2, 2), (28, 14), (2, 26)])
        self.sprites["flag"] = flag

    def _build_mario_sprites(self) -> None:
        def base_mario(cap: int, leg_l: int, leg_r: int, arm_l: int, arm_r: int) -> pygame.Surface:
            surf = self._make_tile()
            surf.fill(COLOR_MARIO_RED, pygame.Rect(3 + cap, 1, 8, 3))
            surf.fill(COLOR_MARIO_BROWN, pygame.Rect(2, 3, 3, 3))
            surf.fill(COLOR_MARIO_SKIN, pygame.Rect(5, 3, 6, 4))
            surf.set_at((8, 4), COLOR_BLACK)
            surf.fill(COLOR_MARIO_BROWN, pygame.Rect(7, 6, 4, 1))
            surf.fill(COLOR_MARIO_RED, pygame.Rect(4, 7, 7, 4))
            surf.fill(COLOR_MARIO_BLUE, pygame.Rect(5, 9, 5, 4))
            surf.set_at((5, 9), COLOR_GOLD)
            surf.set_at((9, 9), COLOR_GOLD)
            surf.fill(COLOR_MARIO_RED, pygame.Rect(2 + arm_l, 7, 2, 4))
            surf.fill(COLOR_MARIO_RED, pygame.Rect(11 + arm_r, 7, 2, 4))
            surf.fill(COLOR_MARIO_BROWN, pygame.Rect(3 + leg_l, 13, 4, 3))
            surf.fill(COLOR_MARIO_BROWN, pygame.Rect(8 + leg_r, 13, 4, 3))
            return self._finalize(surf)

        self.sprites["mario_idle"] = base_mario(0, 0, 0, 0, 0)
        self.sprites["mario_run_0"] = base_mario(0, 1, -1, 1, -1)
        self.sprites["mario_run_1"] = base_mario(0, 0, 0, 0, 0)
        self.sprites["mario_run_2"] = base_mario(0, -1, 2, -1, 1)

        jump_surf = self._make_tile()
        jump_surf.fill(COLOR_MARIO_RED, pygame.Rect(3, 1, 8, 3))
        jump_surf.fill(COLOR_MARIO_SKIN, pygame.Rect(5, 3, 6, 4))
        jump_surf.set_at((8, 4), COLOR_BLACK)
        jump_surf.fill(COLOR_MARIO_BROWN, pygame.Rect(7, 6, 4, 1))
        jump_surf.fill(COLOR_MARIO_BLUE, pygame.Rect(4, 7, 7, 5))
        jump_surf.fill(COLOR_MARIO_RED, pygame.Rect(1, 4, 3, 3))
        jump_surf.fill(COLOR_MARIO_RED, pygame.Rect(11, 8, 3, 3))
        jump_surf.fill(COLOR_MARIO_BROWN, pygame.Rect(2, 12, 4, 3))
        jump_surf.fill(COLOR_MARIO_BROWN, pygame.Rect(10, 10, 4, 3))
        self.sprites["mario_jump"] = self._finalize(jump_surf)

        skid_surf = self._make_tile()
        skid_surf.fill(COLOR_MARIO_RED, pygame.Rect(4, 1, 8, 3))
        skid_surf.fill(COLOR_MARIO_SKIN, pygame.Rect(5, 3, 6, 4))
        skid_surf.set_at((6, 4), COLOR_BLACK)
        skid_surf.fill(COLOR_MARIO_BLUE, pygame.Rect(4, 7, 7, 5))
        skid_surf.fill(COLOR_MARIO_BROWN, pygame.Rect(1, 13, 5, 3))
        skid_surf.fill(COLOR_MARIO_BROWN, pygame.Rect(9, 13, 5, 3))
        self.sprites["mario_skid"] = self._finalize(skid_surf)

        die_surf = self._make_tile()
        die_surf.fill(COLOR_MARIO_RED, pygame.Rect(3, 2, 8, 3))
        die_surf.fill(COLOR_MARIO_SKIN, pygame.Rect(4, 4, 8, 4))
        die_surf.set_at((5, 5), COLOR_BLACK)
        die_surf.set_at((9, 5), COLOR_BLACK)
        die_surf.fill(COLOR_MARIO_BLUE, pygame.Rect(4, 8, 8, 5))
        die_surf.fill(COLOR_MARIO_BROWN, pygame.Rect(2, 13, 4, 3))
        die_surf.fill(COLOR_MARIO_BROWN, pygame.Rect(10, 13, 4, 3))
        self.sprites["mario_die"] = self._finalize(die_surf)

    def _try_load_custom_assets(self) -> None:
        """Loads external PNG files from `assets/` directory if user provides them."""
        if not os.path.isdir(self.asset_dir):
            return
        for file in os.listdir(self.asset_dir):
            if file.endswith(".png"):
                name = os.path.splitext(file)[0]
                full_path = os.path.join(self.asset_dir, file)
                try:
                    loaded = pygame.image.load(full_path).convert_alpha()
                    self.sprites[name] = loaded
                except Exception as exc:
                    print(f"[AssetManager] Notice: Could not load custom sprite {file}: {exc}")


# ==============================================================================
# 4. CAMERA SYSTEM
# ==============================================================================
class Camera:
    """Follows the player smoothly with deadzone centering and boundary clamping."""

    def __init__(self, width: int, height: int, world_width: int, world_height: int) -> None:
        self.viewport = pygame.Rect(0, 0, width, height)
        self.world_width = world_width
        self.world_height = world_height
        self.offset_x = 0.0

    def update(self, target_rect: pygame.Rect) -> None:
        # Keep player roughly in the center-left portion of the screen
        target_x = target_rect.centerx - (self.viewport.width * 0.42)
        self.offset_x += (target_x - self.offset_x) * 0.12

        # Clamp within level bounds
        max_scroll = max(0, self.world_width - self.viewport.width)
        self.offset_x = max(0.0, min(self.offset_x, float(max_scroll)))
        self.viewport.x = int(self.offset_x)

    def apply(self, target: pygame.Rect | pygame.sprite.Sprite) -> pygame.Rect:
        """Transforms world coordinates into screen coordinates."""
        rect = target.rect if isinstance(target, pygame.sprite.Sprite) else target
        return rect.move(-self.viewport.x, -self.viewport.y)


# ==============================================================================
# 5. TILES & COLLECTIBLES
# ==============================================================================
class Tile(pygame.sprite.Sprite):
    """Base solid tile for terrain, pipes, and obstacles."""

    def __init__(self, x: int, y: int, image: pygame.Surface) -> None:
        super().__init__()
        self.image = image
        self.rect = self.image.get_rect(topleft=(x, y))
        self.base_y = y


class BrickBlock(Tile):
    """Brick block that can be bumped from below with a bounce animation."""

    def __init__(self, x: int, y: int, image: pygame.Surface, sound: RetroSoundEngine) -> None:
        super().__init__(x, y, image)
        self.sound = sound
        self.is_bumping = False
        self.bump_offset = 0.0
        self.bump_speed = 0.0

    def bump(self) -> None:
        if not self.is_bumping:
            self.is_bumping = True
            self.bump_offset = 0.0
            self.bump_speed = -6.0
            self.sound.play("bump")

    def update(self) -> None:
        if self.is_bumping:
            self.bump_offset += self.bump_speed
            self.bump_speed += 1.2
            if self.bump_offset >= 0.0:
                self.bump_offset = 0.0
                self.is_bumping = False
            self.rect.y = int(self.base_y + self.bump_offset)


class QuestionBlock(Tile):
    """Question block [?] that dispenses coins and turns into an empty block."""

    def __init__(
        self,
        x: int,
        y: int,
        active_image: pygame.Surface,
        empty_image: pygame.Surface,
        sound: RetroSoundEngine,
        level_ref: Level,
    ) -> None:
        super().__init__(x, y, active_image)
        self.active_image = active_image
        self.empty_image = empty_image
        self.sound = sound
        self.level_ref = level_ref
        self.is_empty = False
        self.is_bumping = False
        self.bump_offset = 0.0
        self.bump_speed = 0.0

    def bump(self) -> None:
        if not self.is_empty and not self.is_bumping:
            self.is_empty = True
            self.image = self.empty_image
            self.is_bumping = True
            self.bump_offset = 0.0
            self.bump_speed = -7.0
            self.sound.play("coin")
            self.level_ref.spawn_bouncing_coin(self.rect.centerx, self.rect.top)
            self.level_ref.coins_collected += 1
            self.level_ref.score += 200

    def update(self) -> None:
        if self.is_bumping:
            self.bump_offset += self.bump_speed
            self.bump_speed += 1.2
            if self.bump_offset >= 0.0:
                self.bump_offset = 0.0
                self.is_bumping = False
            self.rect.y = int(self.base_y + self.bump_offset)


class CollectibleCoin(pygame.sprite.Sprite):
    """Spinning coin floating in the world that can be collected by touching it."""

    def __init__(self, x: int, y: int, asset_mgr: AssetManager) -> None:
        super().__init__()
        self.asset_mgr = asset_mgr
        self.frame = 0
        self.image = self.asset_mgr.sprites[f"coin_{self.frame}"]
        self.rect = self.image.get_rect(topleft=(x, y))
        self.anim_timer = 0

    def update(self) -> None:
        self.anim_timer += 1
        if self.anim_timer % 8 == 0:
            self.frame = (self.frame + 1) % 4
            self.image = self.asset_mgr.sprites[f"coin_{self.frame}"]


class BouncingCoin(pygame.sprite.Sprite):
    """Coin that pops upward out of a question block and disappears."""

    def __init__(self, x: int, y: int, asset_mgr: AssetManager) -> None:
        super().__init__()
        self.asset_mgr = asset_mgr
        self.frame = 0
        self.image = self.asset_mgr.sprites[f"coin_{self.frame}"]
        self.rect = self.image.get_rect(center=(x, y))
        self.vel_y = -9.5
        self.gravity = 0.65
        self.start_y = y
        self.anim_timer = 0

    def update(self) -> None:
        self.vel_y += self.gravity
        self.rect.y += int(self.vel_y)

        self.anim_timer += 1
        if self.anim_timer % 4 == 0:
            self.frame = (self.frame + 1) % 4
            self.image = self.asset_mgr.sprites[f"coin_{self.frame}"]

        if self.vel_y > 0 and self.rect.y >= self.start_y - 12:
            self.kill()


# ==============================================================================
# 6. ENEMY AI (Goomba)
# ==============================================================================
class Goomba(pygame.sprite.Sprite):
    """Autonomous patrolling enemy that reverses upon collision and flattens when stomped."""

    def __init__(self, x: int, y: int, asset_mgr: AssetManager, sound: RetroSoundEngine) -> None:
        super().__init__()
        self.asset_mgr = asset_mgr
        self.sound = sound
        self.image = self.asset_mgr.sprites["goomba_0"]
        self.rect = self.image.get_rect(topleft=(x, y))

        self.pos_x = float(x)
        self.pos_y = float(y)
        self.vel_x = -ENEMY_SPEED
        self.vel_y = 0.0

        self.on_ground = False
        self.is_dead = False
        self.death_timer = 0
        self.anim_timer = 0
        self.anim_frame = 0

    def stomp(self) -> None:
        self.is_dead = True
        self.image = self.asset_mgr.sprites["goomba_squashed"]
        self.sound.play("stomp")

    def update(self, tiles: pygame.sprite.Group) -> None:
        if self.is_dead:
            self.death_timer += 1
            if self.death_timer > 30:
                self.kill()
            return

        # 1. Apply Gravity
        self.vel_y = min(self.vel_y + GRAVITY, TERMINAL_VELOCITY)

        # 2. Horizontal Movement & Wall Collision
        self.pos_x += self.vel_x
        self.rect.x = round(self.pos_x)
        for tile in pygame.sprite.spritecollide(self, tiles, False):
            if self.vel_x > 0:
                self.rect.right = tile.rect.left
                self.pos_x = float(self.rect.x)
                self.vel_x = -self.vel_x
            elif self.vel_x < 0:
                self.rect.left = tile.rect.right
                self.pos_x = float(self.rect.x)
                self.vel_x = -self.vel_x

        # 3. Vertical Movement & Floor Collision
        self.pos_y += self.vel_y
        self.rect.y = round(self.pos_y)
        self.on_ground = False
        for tile in pygame.sprite.spritecollide(self, tiles, False):
            if self.vel_y > 0:
                self.rect.bottom = tile.rect.top
                self.pos_y = float(self.rect.y)
                self.vel_y = 0.0
                self.on_ground = True
            elif self.vel_y < 0:
                self.rect.top = tile.rect.bottom
                self.pos_y = float(self.rect.y)
                self.vel_y = 0.0

        # 4. Walking Animation
        self.anim_timer += 1
        if self.anim_timer % 12 == 0:
            self.anim_frame = (self.anim_frame + 1) % 2
            self.image = self.asset_mgr.sprites[f"goomba_{self.anim_frame}"]


# ==============================================================================
# 7. PLAYER CHARACTER (Mario)
# ==============================================================================
class Player(pygame.sprite.Sprite):
    """Mario player entity with physics, momentum, coyote time, and collision logic."""

    def __init__(self, x: int, y: int, asset_mgr: AssetManager, sound: RetroSoundEngine) -> None:
        super().__init__()
        self.asset_mgr = asset_mgr
        self.sound = sound
        self.image = self.asset_mgr.sprites["mario_idle"]
        self.rect = pygame.Rect(x, y, 26, 32)

        self.pos_x = float(x)
        self.pos_y = float(y)
        self.vel_x = 0.0
        self.vel_y = 0.0

        self.facing_right = True
        self.on_ground = False
        self.is_skidding = False
        self.is_dying = False
        self.has_won = False
        self.death_timer = 0

        # Jump responsiveness
        self.coyote_timer = 0
        self.jump_buffer_timer = 0
        self.jump_held = False

        self.anim_frame = 0
        self.anim_distance = 0.0

    def queue_jump(self) -> None:
        self.jump_buffer_timer = JUMP_BUFFER_FRAMES
        self.jump_held = True

    def release_jump(self) -> None:
        self.jump_held = False
        # Variable Jump Cut: Attenuate upward velocity on early release
        if self.vel_y < -3.0:
            self.vel_y *= JUMP_CUT_MODIFIER

    def kill_player(self) -> None:
        if not self.is_dying and not self.has_won:
            self.is_dying = True
            self.vel_x = 0.0
            self.vel_y = -11.5
            self.image = self.asset_mgr.sprites["mario_die"]
            self.sound.play("die")

    def handle_input(self, keys: pygame.key.ScancodeWrapper) -> None:
        if self.is_dying or self.has_won:
            return

        is_running = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] or keys[pygame.K_x]
        accel = RUN_ACCEL if is_running else WALK_ACCEL
        max_speed = MAX_RUN_SPEED if is_running else MAX_WALK_SPEED

        move_dir = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            move_dir -= 1
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            move_dir += 1

        # Horizontal Acceleration & Skidding
        if move_dir != 0:
            # Detect sharp direction reversals at speed
            if (move_dir > 0 and self.vel_x < -1.0) or (move_dir < 0 and self.vel_x > 1.0):
                self.is_skidding = True
                self.vel_x += move_dir * (accel * 1.8)
                self.vel_x *= SKID_FRICTION
            else:
                self.is_skidding = False
                self.vel_x += move_dir * accel
                self.facing_right = move_dir > 0

            self.vel_x = max(-max_speed, min(self.vel_x, max_speed))
        else:
            self.is_skidding = False
            self.vel_x *= FRICTION
            if abs(self.vel_x) < 0.15:
                self.vel_x = 0.0

    def update(self, tiles: pygame.sprite.Group, level_width: int) -> None:
        # Death animation sequence
        if self.is_dying:
            self.death_timer += 1
            if self.death_timer > 15:
                self.pos_y += self.vel_y
                self.vel_y += GRAVITY * 0.95
                self.rect.y = round(self.pos_y)
            return

        # 1. Update Jump Timers
        if self.on_ground:
            self.coyote_timer = COYOTE_TIME_FRAMES
        elif self.coyote_timer > 0:
            self.coyote_timer -= 1

        if self.jump_buffer_timer > 0:
            self.jump_buffer_timer -= 1

        # Execute buffered jump if coyote time allows
        if self.jump_buffer_timer > 0 and self.coyote_timer > 0:
            self.vel_y = JUMP_FORCE
            self.on_ground = False
            self.coyote_timer = 0
            self.jump_buffer_timer = 0
            self.sound.play("jump")

        # 2. Apply Gravity
        self.vel_y = min(self.vel_y + GRAVITY, TERMINAL_VELOCITY)

        # 3. Horizontal Movement & Axis-X Collision Resolution
        self.pos_x += self.vel_x
        self.pos_x = max(0.0, min(self.pos_x, float(level_width - self.rect.width)))
        self.rect.x = round(self.pos_x)

        for tile in pygame.sprite.spritecollide(self, tiles, False):
            if self.vel_x > 0:
                self.rect.right = tile.rect.left
                self.pos_x = float(self.rect.x)
                self.vel_x = 0.0
            elif self.vel_x < 0:
                self.rect.left = tile.rect.right
                self.pos_x = float(self.rect.x)
                self.vel_x = 0.0

        # 4. Vertical Movement & Axis-Y Collision Resolution
        self.pos_y += self.vel_y
        self.rect.y = round(self.pos_y)
        self.on_ground = False

        for tile in pygame.sprite.spritecollide(self, tiles, False):
            if self.vel_y > 0:
                # Landing on top of a tile
                self.rect.bottom = tile.rect.top
                self.pos_y = float(self.rect.y)
                self.vel_y = 0.0
                self.on_ground = True
            elif self.vel_y < 0:
                # Bonking head on a ceiling block
                self.rect.top = tile.rect.bottom
                self.pos_y = float(self.rect.y)
                self.vel_y = 0.0
                if hasattr(tile, "bump"):
                    tile.bump()

        # 5. Check Pit Fall
        if self.rect.top > SCREEN_HEIGHT + 64:
            self.kill_player()

        # 6. Update Animations
        self._update_animation()

    def _update_animation(self) -> None:
        if not self.on_ground:
            img = self.asset_mgr.sprites["mario_jump"]
        elif self.is_skidding:
            img = self.asset_mgr.sprites["mario_skid"]
        elif abs(self.vel_x) > 0.2:
            self.anim_distance += abs(self.vel_x)
            run_frame = int(self.anim_distance / 12) % 3
            img = self.asset_mgr.sprites[f"mario_run_{run_frame}"]
        else:
            self.anim_distance = 0.0
            img = self.asset_mgr.sprites["mario_idle"]

        if not self.facing_right:
            img = pygame.transform.flip(img, True, False)

        self.image = img


# ==============================================================================
# 8. LEVEL MANAGER & TILEMAP PARSER
# ==============================================================================
class Level:
    """Parses ASCII layouts into game objects and maintains active entity groups."""

    def __init__(self, asset_mgr: AssetManager, sound: RetroSoundEngine) -> None:
        self.asset_mgr = asset_mgr
        self.sound = sound

        self.tiles = pygame.sprite.Group()
        self.enemies = pygame.sprite.Group()
        self.floating_coins = pygame.sprite.Group()
        self.bouncing_coins = pygame.sprite.Group()
        self.goal_sprites = pygame.sprite.Group()

        self.player: Optional[Player] = None
        self.flag_rect: Optional[pygame.Rect] = None
        self.pixel_width = 0
        self.coins_collected = 0
        self.score = 0

    def spawn_bouncing_coin(self, x: int, y: int) -> None:
        self.bouncing_coins.add(BouncingCoin(x, y, self.asset_mgr))

    def load_ascii_map(self, map_data: List[str]) -> None:
        width_tiles = max(len(row) for row in map_data)
        self.pixel_width = width_tiles * TILE_SIZE

        for row_idx, line in enumerate(map_data):
            for col_idx, char in enumerate(line):
                x = col_idx * TILE_SIZE
                y = row_idx * TILE_SIZE

                if char == "G":
                    self.tiles.add(Tile(x, y, self.asset_mgr.sprites["ground"]))
                elif char == "B":
                    self.tiles.add(BrickBlock(x, y, self.asset_mgr.sprites["brick"], self.sound))
                elif char == "?":
                    self.tiles.add(
                        QuestionBlock(
                            x,
                            y,
                            self.asset_mgr.sprites["question"],
                            self.asset_mgr.sprites["empty_block"],
                            self.sound,
                            self,
                        )
                    )
                elif char == "C":
                    self.floating_coins.add(CollectibleCoin(x, y, self.asset_mgr))
                elif char == "[":
                    self.tiles.add(Tile(x, y, self.asset_mgr.sprites["pipe_top_left"]))
                elif char == "]":
                    self.tiles.add(Tile(x, y, self.asset_mgr.sprites["pipe_top_right"]))
                elif char == "{":
                    self.tiles.add(Tile(x, y, self.asset_mgr.sprites["pipe_body_left"]))
                elif char == "}":
                    self.tiles.add(Tile(x, y, self.asset_mgr.sprites["pipe_body_right"]))
                elif char == "E":
                    self.enemies.add(Goomba(x, y, self.asset_mgr, self.sound))
                elif char == "P":
                    self.player = Player(x, y, self.asset_mgr, self.sound)
                elif char == "F":
                    self.goal_sprites.add(Tile(x, y, self.asset_mgr.sprites["pole_top"]))
                elif char == "|":
                    self.goal_sprites.add(Tile(x, y, self.asset_mgr.sprites["flagpole"]))
                    if self.flag_rect is None:
                        self.flag_rect = pygame.Rect(x, y, TILE_SIZE, TILE_SIZE * 8)


# Super Mario Bros. World 1-1 Layout (15 rows, multi-screen scrolling)
# Legend:
#   G = Ground, B = Brick, ? = Question Block, C = Floating Coin
#   [ ] = Pipe Top, { } = Pipe Body, P = Player, E = Goomba, F = Pole Top, | = Pole Body, . = Sky
STAGE_1_1 = [
    "....................................................................................................",
    "....................................................................................................",
    "....................................................................................................",
    "....................................................................................................",
    "....................................................................................................",
    "....................................................................................................",
    "..................................................................................F.................",
    "..................................................................................|.................",
    "..................................................B?B.............................|.................",
    "....................?....B?B?B.......C.C..........................................|.................",
    "..................................[ ]........................[ ]........BBBB......|.................",
    ".............[ ]..................{ }........................{ }..................|.................",
    ".............{ }..................{ }...........E............{ }..................|.................",
    "P............{ }....E.............{ }........GGGGGG..........{ }........E.........|.................",
    "GGGGGGGGGGGGGGGGGGGGGGGGGGGGGG....GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG",
]


# ==============================================================================
# 9. GAME ENGINE & MAIN LOOP
# ==============================================================================
class Game:
    """Master game engine managing the update/draw cycle and application states."""

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Super Mario Bros. - Pygame Platformer")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()

        self.sound = RetroSoundEngine()
        self.assets = AssetManager()
        self.font = pygame.font.SysFont("consolas", 18, bold=True)
        self.font_large = pygame.font.SysFont("consolas", 36, bold=True)

        self.score = 0
        self.coins = 0
        self.lives = 3
        self.time_remaining = 300
        self.frame_counter = 0
        self.is_paused = False
        self.state = "PLAYING"

        self.reset_level()

    def reset_level(self) -> None:
        self.level = Level(self.assets, self.sound)
        self.level.load_ascii_map(STAGE_1_1)
        self.camera = Camera(SCREEN_WIDTH, SCREEN_HEIGHT, self.level.pixel_width, SCREEN_HEIGHT)
        self.state = "PLAYING"
        self.time_remaining = 300

    def run(self) -> None:
        running = True
        while running:
            # 1. Event Handling
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_p:
                        self.is_paused = not self.is_paused
                    elif event.key == pygame.K_r:
                        if self.state == "GAME_OVER":
                            self.lives = 3
                            self.score = 0
                            self.coins = 0
                        self.reset_level()
                    elif event.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_z, pygame.K_w):
                        if self.level.player:
                            self.level.player.queue_jump()
                elif event.type == pygame.KEYUP:
                    if event.key in (pygame.K_SPACE, pygame.K_UP, pygame.K_z, pygame.K_w):
                        if self.level.player:
                            self.level.player.release_jump()

            # 2. Logic Update
            if not self.is_paused:
                self.update()

            # 3. Render Pipeline
            self.draw()
            self.clock.tick(FPS)

        pygame.quit()
        sys.exit()

    def update(self) -> None:
        player = self.level.player
        if not player:
            return

        # Synchronize coins & score earned from level interactions
        if self.level.score > 0:
            self.score += self.level.score
            self.level.score = 0
        if self.level.coins_collected > 0:
            self.coins += self.level.coins_collected
            self.level.coins_collected = 0

        # Countdown Game Timer
        self.frame_counter += 1
        if self.frame_counter % 60 == 0 and self.time_remaining > 0 and self.state == "PLAYING":
            self.time_remaining -= 1
            if self.time_remaining == 0:
                player.kill_player()

        # Update Player Physics
        keys = pygame.key.get_pressed()
        player.handle_input(keys)
        player.update(self.level.tiles, self.level.pixel_width)

        # Update Level Entities
        self.level.tiles.update()
        self.level.floating_coins.update()
        self.level.bouncing_coins.update()
        self.level.enemies.update(self.level.tiles)

        # Update Camera Follow
        self.camera.update(player.rect)

        # Check Floating Coin Collections
        if not player.is_dying and self.state == "PLAYING":
            collected = pygame.sprite.spritecollide(player, self.level.floating_coins, True)
            for _ in collected:
                self.sound.play("coin")
                self.coins += 1
                self.score += 200

        # Check Player vs Goomba Collisions
        if not player.is_dying and self.state == "PLAYING":
            for enemy in self.level.enemies:
                if enemy.is_dead:
                    continue
                if player.rect.colliderect(enemy.rect):
                    # Stomp condition: Mario is falling downward and his bottom is above enemy midpoint
                    if player.vel_y > 0 and player.rect.bottom < enemy.rect.centery + 10:
                        enemy.stomp()
                        player.vel_y = -8.0  # Upward bounce impulse
                        self.score += 200
                    else:
                        player.kill_player()
                        self.lives -= 1
                        if self.lives <= 0:
                            self.state = "GAME_OVER"

        # Check Flagpole Victory
        if (
            self.level.flag_rect
            and player.rect.colliderect(self.level.flag_rect)
            and self.state == "PLAYING"
        ):
            self.state = "STAGE_CLEAR"
            player.has_won = True
            player.vel_x = 0.0
            self.score += self.time_remaining * 50
            self.sound.play("clear")

        # Respawn logic after falling offscreen or death sequence
        if player.is_dying and player.rect.top > SCREEN_HEIGHT + 80:
            if self.lives > 0:
                self.reset_level()
            else:
                self.state = "GAME_OVER"

    def draw_background(self) -> None:
        """Draws sky and parallax background decorations."""
        self.screen.fill(COLOR_SKY)

        # Parallax Clouds
        for i in range(12):
            cloud_x = (i * 240) - int(self.camera.offset_x * 0.35) % 240
            pygame.draw.ellipse(self.screen, COLOR_WHITE, (cloud_x, 50, 70, 30))
            pygame.draw.ellipse(self.screen, COLOR_WHITE, (cloud_x + 20, 40, 50, 30))

        # Parallax Green Hills
        for i in range(8):
            hill_x = (i * 380) - int(self.camera.offset_x * 0.55) % 380
            pygame.draw.polygon(
                self.screen,
                (0, 140, 0),
                [(hill_x, 416), (hill_x + 70, 340), (hill_x + 140, 416)],
            )

    def draw(self) -> None:
        # 1. Parallax Sky & Scenery
        self.draw_background()

        # 2. Level Geometry & Objects
        for tile in self.level.tiles:
            if self.camera.viewport.colliderect(tile.rect):
                self.screen.blit(tile.image, self.camera.apply(tile))

        for goal in self.level.goal_sprites:
            if self.camera.viewport.colliderect(goal.rect):
                self.screen.blit(goal.image, self.camera.apply(goal))

        for coin in self.level.floating_coins:
            if self.camera.viewport.colliderect(coin.rect):
                self.screen.blit(coin.image, self.camera.apply(coin))

        for coin in self.level.bouncing_coins:
            self.screen.blit(coin.image, self.camera.apply(coin))

        for enemy in self.level.enemies:
            if self.camera.viewport.colliderect(enemy.rect):
                self.screen.blit(enemy.image, self.camera.apply(enemy))

        if self.level.player:
            self.screen.blit(self.level.player.image, self.camera.apply(self.level.player))

        # 3. Heads-Up Display (HUD)
        self.draw_hud()

        # 4. State Overlays
        if self.is_paused:
            self._draw_center_message("PAUSED", "(Press P to Resume)")
        elif self.state == "GAME_OVER":
            self._draw_center_message("GAME OVER", "(Press R to Restart)")
        elif self.state == "STAGE_CLEAR":
            self._draw_center_message("STAGE CLEAR!", f"FINAL SCORE: {self.score} (Press R to Replay)")

        pygame.display.flip()

    def draw_hud(self) -> None:
        """Renders the authentic NES status bar."""
        def draw_two_line_stat(label: str, value: str, x: int) -> None:
            lbl_surf = self.font.render(label, True, COLOR_WHITE)
            val_surf = self.font.render(value, True, COLOR_WHITE)
            self.screen.blit(lbl_surf, (x, 10))
            self.screen.blit(val_surf, (x, 28))

        draw_two_line_stat("MARIO", f"{self.score:06d}", 35)
        draw_two_line_stat("COINS", f"*{self.coins:02d}", 225)
        draw_two_line_stat("WORLD", "1-1", 425)
        draw_two_line_stat("TIME", f"{self.time_remaining:03d}", 625)

        lives_surf = self.font.render(f"LIVES: {self.lives}", True, COLOR_WHITE)
        self.screen.blit(lives_surf, (35, SCREEN_HEIGHT - 28))

    def _draw_center_message(self, title: str, subtitle: str) -> None:
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        t_surf = self.font_large.render(title, True, COLOR_WHITE)
        s_surf = self.font.render(subtitle, True, COLOR_GOLD)
        self.screen.blit(t_surf, t_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 20)))
        self.screen.blit(s_surf, s_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 25)))


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    game = Game()
    game.run()

