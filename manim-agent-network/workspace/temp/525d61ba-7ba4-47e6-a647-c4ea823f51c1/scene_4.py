from manim import *

class Scene4(Scene):
    def construct(self):
        # STEP 1 — Title
        title = Text("Real-World Impact", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # STEP 2 — Globe
        globe = Sphere(radius=1.8, resolution=(32, 32)).set_color(BLUE_E).set_opacity(0.7)
        grid_lines = VGroup()
        for i in range(8):
            lat = ParametricFunction(lambda t: globe.radius * np.array([np.cos(t) * np.cos(i * PI / 8), np.sin(i * PI / 8), np.sin(t) * np.cos(i * PI / 8)]), t_range=[0, TAU], stroke_width=1, color=WHITE)
            lon = ParametricFunction(lambda t: globe.radius * np.array([np.cos(i * PI / 4) * np.cos(t), np.sin(t), np.sin(i * PI / 4) * np.cos(t)]), t_range=[0, TAU], stroke_width=1, color=WHITE)
            grid_lines.add(lat, lon)
        globe_group = VGroup(globe, grid_lines)
        self.play(FadeIn(globe_group))
        self.wait(0.5)

        # STEP 3 — Icons
        music = SVGMobject("music.svg") if False else Text("♪", font_size=60, color=YELLOW)
        car = SVGMobject("car.svg") if False else Rectangle(width=1.2, height=0.6, color=GREEN)
        dna = SVGMobject("dna.svg") if False else VGroup(*[Line(ORIGIN, [0, 1.2, 0], stroke_width=4, color=RED).rotate_about_origin(i * PI / 6, axis=OUT) for i in range(6)])
        shield = SVGMobject("shield.svg") if False else Polygon([0, 0.8, 0], [-0.6, -0.4, 0], [0.6, -0.4, 0], color=GRAY)
        icons = VGroup(music, car, dna, shield)
        icons.scale(0.4)
        labels = VGroup(
            Text("Personalization", font_size=24),
            Text("Autonomy", font_size=24),
            Text("Discovery", font_size=24),
            Text("Ethics", font_size=24)
        )
        positions = [UP * 2.5, RIGHT * 2.5, DOWN * 2.5, LEFT * 2.5]
        for icon, label, pos in zip(icons, labels, positions):
            icon.move_to(pos)
            label.next_to(icon, DOWN, buff=0.2)
        self.play(LaggedStart(*[FadeIn(icon) for icon in icons], lag_ratio=0.2))
        self.play(LaggedStart(*[Write(label) for label in labels], lag_ratio=0.2))
        self.wait(0.5)

        # STEP 4 — Data streams
        nodes = [globe.get_center() + 0.8 * pos / np.linalg.norm(pos) for pos in positions]
        streams = VGroup(*[Line(icon.get_center(), node, stroke_width=2, color=WHITE) for icon, node in zip(icons, nodes)])
        self.play(Create(streams), run_time=1.5)
        self.wait(0.5)

        # STEP 5 — Core label
        core_label = Text("HUMAN-CENTERED AI", font_size=32, color=WHITE)
        core_label.move_to(globe.get_center())
        self.play(Write(core_label))
        self.wait(1)

        # STEP 6 — Zoom out and fade
        full_group = VGroup(globe_group, icons, labels, streams, core_label)
        self.play(full_group.animate.scale(0.3).move_to(ORIGIN), run_time=2)
        self.play(FadeOut(full_group))
        self.wait(1)
