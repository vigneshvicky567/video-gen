from manim import *

class Scene1(Scene):
    def construct(self):
        title = Text("Self-Attention", font_size=48).to_edge(UP)
        self.play(FadeIn(title))

        timeline = DashedLine(LEFT * 4, RIGHT * 4, color=WHITE)
        self.play(FadeIn(timeline))

        words = ["The", "cat", "sat", "down"]
        colors = [BLUE_C, GREEN_C, YELLOW_C, PURPLE_C]  # PURPLE_C instead of PINK_C
        circles = []
        labels = []
        positions = [LEFT * 3, LEFT * 1, RIGHT * 1, RIGHT * 3]

        for word, color, pos in zip(words, colors, positions):
            circle = Circle(radius=0.4, color=color, fill_opacity=0.8)
            label = Text(word, font_size=24, color=WHITE)
            circle.move_to(pos)
            label.move_to(pos)
            circles.append(circle)
            labels.append(label)

        group = VGroup(*circles, *labels)
        group.shift(DOWN * 0.5)
        self.play(*[FadeIn(c) for c in circles], *[FadeIn(l) for l in labels])

        arrows = []
        for i in range(4):
            for j in range(4):
                if i != j:
                    start = circles[i].get_center()
                    end = circles[j].get_center()
                    arrow = Arrow(start, end, buff=0.2, stroke_width=2, color=WHITE)
                    arrow.set_opacity(0.5)
                    arrows.append(arrow)

        self.play(*[GrowArrow(arrow) for arrow in arrows])
        self.play(*[arrow.animate.set_color(GRAY).set_opacity(0.3) for arrow in arrows])
        self.wait(1)