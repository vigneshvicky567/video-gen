from manim import *

class Scene1(Scene):
    def construct(self):
        # STEP 1 — Title
        title = Text("Data → Model", font_size=48).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # STEP 2 — DATA stack (3D illusion with cubes)
        data_label = Text("DATA", font_size=36, color=BLUE)
        cubes = VGroup(*[Cube(side_length=0.8, fill_opacity=0.7, stroke_width=2) for _ in range(12)])
        cubes.arrange_in_grid(3, 4, buff=0.2).set_color(BLUE).set_stroke(BLUE_E)
        data_group = VGroup(data_label, cubes).arrange(DOWN, buff=0.3).scale(0.6).shift(LEFT * 4)
        self.play(FadeIn(data_group, shift=UP))
        self.wait(0.5)

        # STEP 3 — Traditional code gear (built with Manim shapes)
        gear = RegularPolygon(8, radius=0.8, color=GOLD, fill_opacity=1, stroke_width=2)
        gear_label = Text("TRADITIONAL\nCODE", font_size=24).next_to(gear, DOWN)
        gear_group = VGroup(gear, gear_label).shift(LEFT * 1.5)
        self.play(FadeIn(gear_group))
        self.wait(0.5)

        # STEP 4 — Hand cursor dragging tiny rules
        hand = Triangle(color=WHITE, fill_opacity=1).scale(0.3).rotate(PI).next_to(gear, LEFT, buff=0.2)
        rules = VGroup(*[Text("rule", font_size=16, color=WHITE) for _ in range(3)]).arrange(DOWN, buff=0.1).next_to(hand, LEFT, buff=0.1)
        self.play(FadeIn(hand), *[FadeIn(r) for r in rules])
        self.play(hand.animate.shift(RIGHT * 0.5), *[r.animate.shift(RIGHT * 0.5) for r in rules])
        self.wait(0.5)

        # STEP 5 — ML Model brain mesh
        brain = Circle(radius=0.8, color=GREEN, stroke_width=2)
        inner = Circle(radius=0.6, color=GREEN, stroke_width=2)
        core = Circle(radius=0.4, color=GREEN, stroke_width=2)
        brain_mesh = VGroup(brain, inner, core)
        brain_label = Text("ML MODEL", font_size=30, color=GREEN).next_to(brain_mesh, DOWN)
        brain_group = VGroup(brain_mesh, brain_label).shift(RIGHT * 3)
        self.play(FadeIn(brain_group))
        self.wait(0.5)

        # STEP 6 — Arrow from data to brain
        arrow = Arrow(data_group.get_right(), brain_group.get_left(), buff=0.2, color=GREEN)
        self.play(GrowArrow(arrow))
        self.wait(0.5)

        # Fade out traditional elements
        self.play(FadeOut(gear_group), FadeOut(hand), *[FadeOut(r) for r in rules])
        self.wait(0.5)

        # Pulse brain
        self.play(brain_mesh.animate.scale(1.1), rate_func=there_and_back, run_time=0.5)
        self.play(brain_mesh.animate.scale(1.1), rate_func=there_and_back, run_time=0.5)
        self.wait(1)

        # Fade everything
        all_group = VGroup(title, data_group, brain_group, arrow)
        self.play(FadeOut(all_group))
        self.wait(0.5)