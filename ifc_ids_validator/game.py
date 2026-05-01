# game.py
from __future__ import annotations

import math
import os
import random
import sys
import getpass
from dataclasses import dataclass
from pathlib import Path

import pygame
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment


WIDTH, HEIGHT = 960, 560
FPS = 120

RESULT_DIR = Path(r"T:\BIM отдел\Шебордаев\programming\game_result")
RESULT_FILE = RESULT_DIR / "leaderboard.xlsx"

BG = (8, 12, 24)
WHITE = (245, 248, 255)
TEXT = (225, 235, 255)
MUTED = (125, 150, 190)
CYAN = (54, 220, 255)
BLUE = (60, 120, 255)
PURPLE = (165, 90, 255)
PINK = (255, 70, 165)
RED = (255, 70, 85)
ORANGE = (255, 165, 70)
GREEN = (70, 245, 160)
YELLOW = (255, 230, 90)


def clamp(v, a, b):
    return max(a, min(b, v))


def length(x, y):
    return math.hypot(x, y)


def normalize(x, y):
    l = math.hypot(x, y)
    if l <= 0.0001:
        return 0, 0
    return x / l, y / l


def lerp(a, b, t):
    return a + (b - a) * t


def draw_text(surface, font, text, x, y, color=TEXT, center=False):
    img = font.render(text, True, color)
    r = img.get_rect()
    if center:
        r.center = (x, y)
    else:
        r.topleft = (x, y)
    surface.blit(img, r)
    return r


def get_windows_user():
    return os.environ.get("USERNAME") or getpass.getuser() or "Unknown"


def load_leaderboard():
    try:
        if not RESULT_FILE.exists():
            return []

        wb = load_workbook(RESULT_FILE)
        ws = wb.active

        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue

            user = str(row[0])
            score = int(row[1] or 0)
            rows.append((user, score))

        rows.sort(key=lambda x: x[1], reverse=True)
        return rows

    except Exception:
        return []


def save_score_to_excel(user, score):
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    if RESULT_FILE.exists():
        wb = load_workbook(RESULT_FILE)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Лидеры"
        ws["A1"] = "Пользователь"
        ws["B1"] = "Максимальные очки"

    existing_row = None
    existing_best = 0

    for row in range(2, ws.max_row + 1):
        name = ws.cell(row=row, column=1).value
        if str(name).lower() == str(user).lower():
            existing_row = row
            existing_best = int(ws.cell(row=row, column=2).value or 0)
            break

    if existing_row:
        if score > existing_best:
            ws.cell(row=existing_row, column=2).value = score
    else:
        new_row = ws.max_row + 1
        ws.cell(row=new_row, column=1).value = user
        ws.cell(row=new_row, column=2).value = score

    data = []
    for row in range(2, ws.max_row + 1):
        name = ws.cell(row=row, column=1).value
        value = ws.cell(row=row, column=2).value
        if name:
            data.append((str(name), int(value or 0)))

    data.sort(key=lambda x: x[1], reverse=True)

    ws.delete_rows(2, ws.max_row)

    for i, (name, value) in enumerate(data, start=2):
        ws.cell(row=i, column=1).value = name
        ws.cell(row=i, column=2).value = value

    header_fill = PatternFill("solid", fgColor="0B4EA2")
    header_font = Font(color="FFFFFF", bold=True)
    border = Border(
        left=Side(style="thin", color="D6DFEB"),
        right=Side(style="thin", color="D6DFEB"),
        top=Side(style="thin", color="D6DFEB"),
        bottom=Side(style="thin", color="D6DFEB")
    )

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=2):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(horizontal="center" if cell.column == 2 else "left")

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 22
    ws.freeze_panes = "A2"

    wb.save(RESULT_FILE)


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    color: tuple[int, int, int]
    life: float
    max_life: float
    glow: bool = True

    def update(self, dt):
        self.life -= dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= 0.985
        self.vy *= 0.985
        return self.life > 0

    def draw(self, surf):
        k = clamp(self.life / self.max_life, 0, 1)
        r = max(1, int(self.radius * k))
        color = tuple(int(c * k) for c in self.color)
        if self.glow:
            pygame.draw.circle(surf, tuple(int(c * 0.35) for c in color), (int(self.x), int(self.y)), r * 4)
        pygame.draw.circle(surf, color, (int(self.x), int(self.y)), r)


class Player:
    def __init__(self):
        self.x = WIDTH / 2
        self.y = HEIGHT / 2
        self.vx = 0
        self.vy = 0
        self.radius = 17
        self.speed = 520
        self.accel = 13
        self.hp = 100
        self.max_hp = 100
        self.energy = 100
        self.max_energy = 100
        self.dash_cd = 0
        self.invuln = 0
        self.angle = 0

    def update(self, dt, keys, mouse_buttons):
        ix = int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT])
        iy = int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP])
        nx, ny = normalize(ix, iy)

        self.vx = lerp(self.vx, nx * self.speed, min(1, self.accel * dt))
        self.vy = lerp(self.vy, ny * self.speed, min(1, self.accel * dt))

        self.x += self.vx * dt
        self.y += self.vy * dt

        self.x = clamp(self.x, 30, WIDTH - 30)
        self.y = clamp(self.y, 30, HEIGHT - 30)

        self.energy = min(self.max_energy, self.energy + 22 * dt)
        self.dash_cd = max(0, self.dash_cd - dt)
        self.invuln = max(0, self.invuln - dt)

        if length(self.vx, self.vy) > 30:
            self.angle = math.atan2(self.vy, self.vx)

    def dash(self, particles):
        if self.dash_cd > 0 or self.energy < 32:
            return

        mx, my = pygame.mouse.get_pos()
        dx, dy = normalize(mx - self.x, my - self.y)

        if dx == 0 and dy == 0:
            dx, dy = math.cos(self.angle), math.sin(self.angle)

        self.x += dx * 115
        self.y += dy * 115
        self.x = clamp(self.x, 30, WIDTH - 30)
        self.y = clamp(self.y, 30, HEIGHT - 30)

        self.energy -= 32
        self.dash_cd = 0.42
        self.invuln = 0.28

        for _ in range(34):
            a = math.atan2(-dy, -dx) + random.uniform(-0.75, 0.75)
            s = random.uniform(90, 480)
            particles.append(Particle(
                self.x, self.y,
                math.cos(a) * s,
                math.sin(a) * s,
                random.uniform(2, 6),
                random.choice([CYAN, BLUE, PURPLE]),
                random.uniform(0.18, 0.45),
                0.45
            ))

    def damage(self, amount, particles):
        if self.invuln > 0:
            return False

        self.hp -= amount
        self.invuln = 0.65

        for _ in range(28):
            a = random.uniform(0, math.tau)
            s = random.uniform(80, 360)
            particles.append(Particle(
                self.x, self.y,
                math.cos(a) * s,
                math.sin(a) * s,
                random.uniform(2, 7),
                random.choice([RED, PINK, ORANGE]),
                random.uniform(0.25, 0.6),
                0.6
            ))
        return True

    def draw(self, surf, t):
        pulse = 1 + math.sin(t * 8) * 0.04
        r = int(self.radius * pulse)

        if self.invuln > 0:
            pygame.draw.circle(surf, (80, 190, 255), (int(self.x), int(self.y)), r + 12, 2)

        pygame.draw.circle(surf, (20, 80, 150), (int(self.x), int(self.y)), r + 12)
        pygame.draw.circle(surf, CYAN, (int(self.x), int(self.y)), r)
        pygame.draw.circle(surf, WHITE, (int(self.x - 5), int(self.y - 6)), 5)

        nose_x = self.x + math.cos(self.angle) * 25
        nose_y = self.y + math.sin(self.angle) * 25
        pygame.draw.line(surf, WHITE, (self.x, self.y), (nose_x, nose_y), 4)


class Enemy:
    def __init__(self, kind, x, y):
        self.kind = kind
        self.x = x
        self.y = y
        self.vx = 0
        self.vy = 0
        self.dead = False
        self.flash = 0

        if kind == "chaser":
            self.radius = 15
            self.speed = 125
            self.hp = 20
            self.color = RED
            self.value = 12
        elif kind == "speeder":
            self.radius = 11
            self.speed = 235
            self.hp = 10
            self.color = ORANGE
            self.value = 18
        elif kind == "tank":
            self.radius = 26
            self.speed = 72
            self.hp = 55
            self.color = PURPLE
            self.value = 35
        else:
            self.radius = 14
            self.speed = 110
            self.hp = 15
            self.color = PINK
            self.value = 15

    def update(self, dt, player, enemies):
        dx, dy = normalize(player.x - self.x, player.y - self.y)

        wobble = math.sin((self.x + self.y) * 0.02 + pygame.time.get_ticks() * 0.006) * 0.8
        tx = dx * math.cos(wobble) - dy * math.sin(wobble)
        ty = dx * math.sin(wobble) + dy * math.cos(wobble)

        self.vx = lerp(self.vx, tx * self.speed, min(1, 5 * dt))
        self.vy = lerp(self.vy, ty * self.speed, min(1, 5 * dt))

        self.x += self.vx * dt
        self.y += self.vy * dt

        for other in enemies:
            if other is self or other.dead:
                continue
            dxo = self.x - other.x
            dyo = self.y - other.y
            d = length(dxo, dyo)
            min_d = self.radius + other.radius + 4
            if 0 < d < min_d:
                nx, ny = dxo / d, dyo / d
                push = (min_d - d) * 0.5
                self.x += nx * push
                self.y += ny * push

        self.flash = max(0, self.flash - dt)

    def hit(self, damage):
        self.hp -= damage
        self.flash = 0.08
        if self.hp <= 0:
            self.dead = True

    def draw(self, surf, t):
        color = WHITE if self.flash > 0 else self.color
        x, y = int(self.x), int(self.y)

        pygame.draw.circle(surf, tuple(int(c * 0.25) for c in color), (x, y), self.radius * 3)
        pygame.draw.circle(surf, color, (x, y), self.radius)

        if self.kind == "tank":
            pygame.draw.circle(surf, (40, 20, 70), (x, y), self.radius - 8)
        elif self.kind == "speeder":
            pygame.draw.polygon(
                surf,
                WHITE,
                [
                    (x + math.cos(t * 8) * 4, y - 5),
                    (x + 7, y + 5),
                    (x - 7, y + 5),
                ]
            )
        else:
            pygame.draw.circle(surf, (30, 10, 20), (x - 5, y - 3), 3)
            pygame.draw.circle(surf, (30, 10, 20), (x + 5, y - 3), 3)


class Orb:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.r = 8
        self.phase = random.random() * math.tau
        self.dead = False

    def update(self, dt, player):
        d = length(player.x - self.x, player.y - self.y)
        if d < 135:
            nx, ny = normalize(player.x - self.x, player.y - self.y)
            self.x += nx * 360 * dt
            self.y += ny * 360 * dt

        if d < player.radius + self.r + 8:
            self.dead = True
            return True
        return False

    def draw(self, surf, t):
        r = self.r + math.sin(t * 8 + self.phase) * 2
        pygame.draw.circle(surf, (30, 90, 70), (int(self.x), int(self.y)), int(r * 3))
        pygame.draw.circle(surf, GREEN, (int(self.x), int(self.y)), int(r))
        pygame.draw.circle(surf, WHITE, (int(self.x - 2), int(self.y - 2)), 2)


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("IFC CHECKER — Neon Core")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.DOUBLEBUF)
        self.clock = pygame.time.Clock()

        self.font_big = pygame.font.SysFont("Segoe UI", 44, bold=True)
        self.font_mid = pygame.font.SysFont("Segoe UI", 24, bold=True)
        self.font = pygame.font.SysFont("Segoe UI", 18)
        self.font_small = pygame.font.SysFont("Segoe UI", 14)

        self.surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.username = get_windows_user()
        self.leaderboard = load_leaderboard()
        self.score_saved = False

        self.reset()

    def reset(self):
        self.player = Player()
        self.enemies = []
        self.particles = []
        self.orbs = []
        self.score = 0
        self.best = max([s for _, s in self.leaderboard], default=0)
        self.t = 0
        self.wave = 1
        self.spawn_timer = 0.5
        self.shot_timer = 0
        self.state = "menu"
        self.shake = 0
        self.combo = 1
        self.combo_timer = 0
        self.score_saved = False
        self.gameover_timer = 0
        self.shake_time = 0
        self.shake_duration = 1.5

        self.stars = []
        for _ in range(120):
            self.stars.append([
                random.uniform(0, WIDTH),
                random.uniform(0, HEIGHT),
                random.uniform(0.2, 1.0),
                random.choice([CYAN, BLUE, PURPLE, WHITE])
            ])

    def spawn_enemy(self):
        side = random.randint(0, 3)
        margin = 50
        if side == 0:
            x, y = random.uniform(0, WIDTH), -margin
        elif side == 1:
            x, y = WIDTH + margin, random.uniform(0, HEIGHT)
        elif side == 2:
            x, y = random.uniform(0, WIDTH), HEIGHT + margin
        else:
            x, y = -margin, random.uniform(0, HEIGHT)

        kind = random.choices(
            ["chaser", "speeder", "tank"],
            weights=[58, 30 + self.wave, max(5, self.wave * 2)],
            k=1
        )[0]
        self.enemies.append(Enemy(kind, x, y))

    def shoot(self):
        mx, my = pygame.mouse.get_pos()
        dx, dy = normalize(mx - self.player.x, my - self.player.y)

        if dx == 0 and dy == 0:
            return

        self.shot_timer = 0.095

        hit_enemy = None
        best_proj = 999999

        for enemy in self.enemies:
            ex = enemy.x - self.player.x
            ey = enemy.y - self.player.y
            proj = ex * dx + ey * dy

            if proj < 0:
                continue

            closest_x = self.player.x + dx * proj
            closest_y = self.player.y + dy * proj
            dist = length(enemy.x - closest_x, enemy.y - closest_y)

            if dist < enemy.radius + 8 and proj < best_proj:
                best_proj = proj
                hit_enemy = enemy

        end_x = self.player.x + dx * 760
        end_y = self.player.y + dy * 760

        if hit_enemy:
            end_x, end_y = hit_enemy.x, hit_enemy.y
            hit_enemy.hit(14)

            for _ in range(12):
                a = random.uniform(0, math.tau)
                s = random.uniform(80, 330)
                self.particles.append(Particle(
                    hit_enemy.x, hit_enemy.y,
                    math.cos(a) * s,
                    math.sin(a) * s,
                    random.uniform(2, 6),
                    hit_enemy.color,
                    random.uniform(0.15, 0.38),
                    0.38
                ))

            if hit_enemy.dead:
                self.score += int(hit_enemy.value * self.combo)
                self.combo = min(8, self.combo + 0.25)
                self.combo_timer = 2.1
                self.shake = max(self.shake, 3.5)

                if random.random() < 0.75:
                    self.orbs.append(Orb(hit_enemy.x, hit_enemy.y))

                for _ in range(24):
                    a = random.uniform(0, math.tau)
                    s = random.uniform(120, 480)
                    self.particles.append(Particle(
                        hit_enemy.x, hit_enemy.y,
                        math.cos(a) * s,
                        math.sin(a) * s,
                        random.uniform(2, 8),
                        random.choice([hit_enemy.color, CYAN, WHITE]),
                        random.uniform(0.22, 0.6),
                        0.6
                    ))

        self.laser = (self.player.x, self.player.y, end_x, end_y, 0.045)

    def update(self, dt):
        self.t += dt

        if self.state == "gameover":
            self.shake_time += dt

        if self.state != "play":
            if self.state == "gameover":
                self.gameover_timer += dt

            for p in list(self.particles):
                if not p.update(dt):
                    self.particles.remove(p)
            return

        keys = pygame.key.get_pressed()
        mouse = pygame.mouse.get_pressed()

        self.player.update(dt, keys, mouse)

        if mouse[0] and self.shot_timer <= 0:
            self.shoot()

        if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] or mouse[2]:
            self.player.dash(self.particles)

        self.shot_timer = max(0, self.shot_timer - dt)

        self.spawn_timer -= dt
        self.wave = 1 + self.score // 250

        if self.spawn_timer <= 0:
            self.spawn_enemy()
            self.spawn_timer = max(0.18, 0.95 - self.wave * 0.045)

        while len(self.enemies) < min(12 + self.wave * 2, 7 + self.wave):
            if random.random() < 0.015:
                self.spawn_enemy()
            else:
                break

        for enemy in list(self.enemies):
            enemy.update(dt, self.player, self.enemies)

            if length(enemy.x - self.player.x, enemy.y - self.player.y) < enemy.radius + self.player.radius:
                if self.player.damage(13 if enemy.kind != "tank" else 22, self.particles):
                    self.shake = max(self.shake, 8)
                    enemy.hit(999)

            if enemy.dead:
                self.enemies.remove(enemy)

        for orb in list(self.orbs):
            if orb.update(dt, self.player):
                self.score += 8
                self.player.energy = min(self.player.max_energy, self.player.energy + 18)
                self.player.hp = min(self.player.max_hp, self.player.hp + 3)
                self.orbs.remove(orb)

        for p in list(self.particles):
            if not p.update(dt):
                self.particles.remove(p)

        self.combo_timer -= dt
        if self.combo_timer <= 0:
            self.combo = 1

        self.shake *= 0.88

        if self.player.hp <= 0:
            self.game_over()

    def game_over(self):
        if self.score_saved:
            return

        self.score_saved = True

        try:
            save_score_to_excel(self.username, self.score)
            self.leaderboard = load_leaderboard()
            self.best = max([s for _, s in self.leaderboard], default=self.score)
        except Exception:
            pass

        self.state = "gameover"
        self.shake = 18
        self.shake_time = 0

        for _ in range(120):
            a = random.uniform(0, math.tau)
            s = random.uniform(100, 700)
            self.particles.append(Particle(
                self.player.x, self.player.y,
                math.cos(a) * s,
                math.sin(a) * s,
                random.uniform(2, 9),
                random.choice([RED, PINK, CYAN, WHITE]),
                random.uniform(0.35, 1.0),
                1.0
            ))

    def draw_background(self, surf):
        surf.fill(BG)

        for star in self.stars:
            x, y, z, color = star
            sx = (x + math.sin(self.t * z) * 12) % WIDTH
            sy = (y + self.t * 12 * z) % HEIGHT
            c = tuple(int(v * z) for v in color)
            pygame.draw.circle(surf, c, (int(sx), int(sy)), max(1, int(2 * z)))

        grid_color = (18, 34, 70)
        offset = (self.t * 30) % 40

        for x in range(-40, WIDTH + 40, 40):
            pygame.draw.line(surf, grid_color, (x, 0), (x + 120, HEIGHT), 1)

        for y in range(int(offset), HEIGHT, 40):
            pygame.draw.line(surf, grid_color, (0, y), (WIDTH, y), 1)

        pygame.draw.circle(surf, (9, 25, 52), (WIDTH // 2, HEIGHT // 2), 230, 2)
        pygame.draw.circle(surf, (12, 30, 65), (WIDTH // 2, HEIGHT // 2), 150, 1)

    def draw_ui(self, surf):
        draw_text(surf, self.font_mid, f"SCORE {self.score}", 22, 18, WHITE)
        draw_text(surf, self.font_small, f"BEST {self.best}", 24, 48, MUTED)
        draw_text(surf, self.font_small, f"USER {self.username}", 24, 68, MUTED)
        draw_text(surf, self.font_small, f"WAVE {self.wave}", WIDTH - 95, 22, MUTED)

        self.bar(surf, 22, HEIGHT - 38, 210, 12, self.player.hp / self.player.max_hp, RED, "HP")
        self.bar(surf, 252, HEIGHT - 38, 210, 12, self.player.energy / self.player.max_energy, CYAN, "ENERGY")

        if self.combo > 1:
            draw_text(surf, self.font_mid, f"x{self.combo:.1f}", WIDTH // 2, 26, YELLOW, center=True)

        draw_text(
            surf,
            self.font_small,
            "WASD/стрелки — движение   ЛКМ — стрелять   Shift/ПКМ — рывок   Esc — меню",
            WIDTH // 2,
            HEIGHT - 18,
            MUTED,
            center=True
        )

    def bar(self, surf, x, y, w, h, k, color, label):
        k = clamp(k, 0, 1)
        pygame.draw.rect(surf, (22, 32, 55), (x, y, w, h), border_radius=8)
        pygame.draw.rect(surf, color, (x, y, int(w * k), h), border_radius=8)
        pygame.draw.rect(surf, (65, 85, 125), (x, y, w, h), 1, border_radius=8)
        draw_text(surf, self.font_small, label, x, y - 18, MUTED)

    def draw_menu(self, surf):
        draw_text(surf, self.font_big, "NEON CORE", WIDTH // 2, 155, CYAN, center=True)
        draw_text(surf, self.font, "Мини-игра для IFC CHECKER", WIDTH // 2, 205, MUTED, center=True)
        draw_text(surf, self.font_mid, "Нажми ПРОБЕЛ или ЛКМ, чтобы начать", WIDTH // 2, 270, WHITE, center=True)
        draw_text(surf, self.font_small, f"Текущий пользователь: {self.username}", WIDTH // 2, 310, MUTED, center=True)

    def draw_leaderboard(self, surf):
        panel = pygame.Rect(270, 105, 420, 350)
        pygame.draw.rect(surf, (12, 20, 40), panel, border_radius=18)
        pygame.draw.rect(surf, (60, 120, 255), panel, 2, border_radius=18)

        draw_text(surf, self.font_mid, "ТАБЛИЦА ЛИДЕРОВ", WIDTH // 2, 130, CYAN, center=True)

        rows = self.leaderboard[:10]
        if not rows:
            draw_text(surf, self.font, "Пока нет результатов", WIDTH // 2, 260, MUTED, center=True)
            return

        y = 175
        for i, (user, score) in enumerate(rows, start=1):
            color = YELLOW if user.lower() == self.username.lower() else WHITE
            draw_text(surf, self.font, f"{i}. {user}", 305, y, color)
            draw_text(surf, self.font, str(score), 650, y, color, center=False)
            y += 25

    def draw_gameover(self, surf):
        draw_text(surf, self.font_big, "СИСТЕМА ПОВРЕЖДЕНА", WIDTH // 2, 58, RED, center=True)
        draw_text(surf, self.font_mid, f"Твои очки: {self.score}", WIDTH // 2, 92, WHITE, center=True)
        self.draw_leaderboard(surf)
        if self.gameover_timer < 3.0:
            wait_text = f"Новая попытка будет доступна через {3.0 - self.gameover_timer:.1f} сек."
            draw_text(surf, self.font, wait_text, WIDTH // 2, 490, MUTED, center=True)
        else:
            draw_text(surf, self.font, "Enter / ЛКМ — новая попытка", WIDTH // 2, 490, MUTED, center=True)

    def draw(self):
        ox = oy = 0

        if self.state == "gameover":
            if self.shake_time < self.shake_duration:
                k = 1 - self.shake_time / self.shake_duration
                strength = max(1, int(14 * k))
                ox = random.randint(-strength, strength)
                oy = random.randint(-strength, strength)
        else:
            if self.shake > 0.4:
                ox = random.randint(-int(self.shake), int(self.shake))
                oy = random.randint(-int(self.shake), int(self.shake))

        self.surface.fill((0, 0, 0, 0))
        self.draw_background(self.surface)

        for orb in self.orbs:
            orb.draw(self.surface, self.t)

        for enemy in self.enemies:
            enemy.draw(self.surface, self.t)

        for p in self.particles:
            p.draw(self.surface)

        if self.state == "play":
            self.player.draw(self.surface, self.t)

        if hasattr(self, "laser"):
            x1, y1, x2, y2, life = self.laser
            life -= 1 / FPS
            if life > 0:
                self.laser = (x1, y1, x2, y2, life)
                pygame.draw.line(self.surface, (150, 240, 255), (x1, y1), (x2, y2), 5)
                pygame.draw.line(self.surface, WHITE, (x1, y1), (x2, y2), 2)
            else:
                del self.laser

        self.draw_ui(self.surface)

        if self.state == "menu":
            self.draw_menu(self.surface)
        elif self.state == "gameover":
            self.draw_gameover(self.surface)

        self.screen.fill(BG)
        self.screen.blit(self.surface, (ox, oy))
        pygame.display.flip()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.state == "play":
                        self.state = "menu"

                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    if self.state == "menu":
                        self.state = "play"
                    elif self.state == "gameover":
                        if self.gameover_timer >= 3.0:
                            self.reset()
                            self.state = "play"

            if event.type == pygame.MOUSEBUTTONDOWN:
                if self.state == "menu":
                    self.state = "play"
                elif self.state == "gameover":
                    if self.gameover_timer >= 3.0:
                        self.reset()
                        self.state = "play"

    def run(self):
        while True:
            dt = self.clock.tick(FPS) / 1000
            dt = min(dt, 1 / 45)

            self.handle_events()
            self.update(dt)
            self.draw()


if __name__ == "__main__":
    Game().run()