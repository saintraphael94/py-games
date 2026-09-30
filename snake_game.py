"""A playable Snake game implemented with Python's built-in turtle module.

Run from a desktop Python installation with:
    python snake_game.py
"""

from __future__ import annotations

import random
import turtle


# Window and game-play settings are kept together for easy adjustment.
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 600
STEP_SIZE = 20
MOVE_DELAY_MS = 110


class SnakeGame:
    """Owns the turtle window, game objects, score, and update loop."""

    def __init__(self) -> None:
        self.screen = turtle.Screen()
        self.screen.title("Snake")
        self.screen.setup(width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        self.screen.bgcolor("black")
        self.screen.tracer(0)  # Draw a complete frame at once to avoid flicker.

        self.snake: list[turtle.Turtle] = []
        self.direction = "stop"
        self.score = 0
        self.game_over = False

        self.food = self._make_turtle("red", "circle")
        self.food.shapesize(0.75, 0.75)

        self.score_writer = turtle.Turtle(visible=False)
        self.score_writer.color("white")
        self.score_writer.penup()
        self.score_writer.goto(0, WINDOW_HEIGHT // 2 - 35)

        self.message_writer = turtle.Turtle(visible=False)
        self.message_writer.color("white")
        self.message_writer.penup()

        self._bind_keys()
        self._reset_game()

    @staticmethod
    def _make_turtle(color: str, shape: str) -> turtle.Turtle:
        """Create a stationary, pen-up turtle used by the game."""
        item = turtle.Turtle(shape=shape)
        item.color(color)
        item.penup()
        item.speed(0)
        return item

    def _bind_keys(self) -> None:
        """Bind both arrow keys and WASD, plus a restart command."""
        self.screen.listen()
        self.screen.onkeypress(lambda: self._set_direction("up"), "Up")
        self.screen.onkeypress(lambda: self._set_direction("down"), "Down")
        self.screen.onkeypress(lambda: self._set_direction("left"), "Left")
        self.screen.onkeypress(lambda: self._set_direction("right"), "Right")
        self.screen.onkeypress(lambda: self._set_direction("up"), "w")
        self.screen.onkeypress(lambda: self._set_direction("down"), "s")
        self.screen.onkeypress(lambda: self._set_direction("left"), "a")
        self.screen.onkeypress(lambda: self._set_direction("right"), "d")
        self.screen.onkeypress(self._reset_game, "r")

    def _set_direction(self, new_direction: str) -> None:
        """Change direction unless it would make the snake reverse into itself."""
        opposites = {
            "up": "down",
            "down": "up",
            "left": "right",
            "right": "left",
        }
        if not self.game_over and opposites.get(self.direction) != new_direction:
            self.direction = new_direction

    def _reset_game(self) -> None:
        """Remove the old snake and restore the initial game state."""
        for segment in self.snake:
            segment.hideturtle()
        self.snake.clear()

        head = self._make_turtle("lime", "square")
        self.snake.append(head)
        self.direction = "stop"
        self.score = 0
        self.game_over = False
        self.message_writer.clear()
        self._place_food()
        self._draw_score()
        self.screen.update()

    def _place_food(self) -> None:
        """Put food on the grid, avoiding a square occupied by the snake."""
        half_width = WINDOW_WIDTH // 2 - STEP_SIZE
        half_height = WINDOW_HEIGHT // 2 - STEP_SIZE

        while True:
            x = random.randrange(-half_width, half_width + 1, STEP_SIZE)
            y = random.randrange(-half_height, half_height + 1, STEP_SIZE)
            if all(segment.distance(x, y) > STEP_SIZE / 2 for segment in self.snake):
                self.food.goto(x, y)
                return

    def _draw_score(self) -> None:
        """Refresh the score at the top of the window."""
        self.score_writer.clear()
        self.score_writer.write(
            f"Score: {self.score}", align="center", font=("Arial", 16, "bold")
        )

    def _move_snake(self) -> None:
        """Shift each body segment forward, then advance the head one grid square."""
        for index in range(len(self.snake) - 1, 0, -1):
            self.snake[index].goto(self.snake[index - 1].position())

        head = self.snake[0]
        moves = {
            "up": (0, STEP_SIZE),
            "down": (0, -STEP_SIZE),
            "left": (-STEP_SIZE, 0),
            "right": (STEP_SIZE, 0),
        }
        dx, dy = moves[self.direction]
        head.goto(head.xcor() + dx, head.ycor() + dy)

    def _grow_snake(self) -> None:
        """Append a body segment; it will follow correctly on the next movement."""
        segment = self._make_turtle("green", "square")
        segment.goto(self.snake[-1].position())
        self.snake.append(segment)

    def _hits_wall(self) -> bool:
        """Return True when the head leaves the playable window area."""
        head = self.snake[0]
        return (
            abs(head.xcor()) >= WINDOW_WIDTH / 2
            or abs(head.ycor()) >= WINDOW_HEIGHT / 2
        )

    def _hits_body(self) -> bool:
        """Return True when the head overlaps a body segment."""
        return any(self.snake[0].distance(segment) < STEP_SIZE / 2 for segment in self.snake[1:])

    def _end_game(self) -> None:
        """Freeze play and display a restart instruction."""
        self.game_over = True
        self.message_writer.goto(0, 0)
        self.message_writer.write(
            "Game Over - Press R to restart",
            align="center",
            font=("Arial", 18, "bold"),
        )

    def _game_loop(self) -> None:
        """Perform one frame, then schedule the next without blocking turtle events."""
        if not self.game_over and self.direction != "stop":
            self._move_snake()

            if self._hits_wall() or self._hits_body():
                self._end_game()
            elif self.snake[0].distance(self.food) < STEP_SIZE:
                self._grow_snake()
                self.score += 1
                self._draw_score()
                self._place_food()

        self.screen.update()
        self.screen.ontimer(self._game_loop, MOVE_DELAY_MS)

    def run(self) -> None:
        """Start the non-blocking loop and hand control to turtle's event system."""
        self._game_loop()
        self.screen.mainloop()


if __name__ == "__main__":
    SnakeGame().run()
