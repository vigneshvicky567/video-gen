from manim import *

class Scene2(Scene):
    def construct(self):
        title = Text("A Neural Network", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Layer positions
        in_pos = [UP*2.5 + LEFT*3, UP*2.5, UP*2.5 + RIGHT*3]
        hid_pos = [UP*0.5 + LEFT*2, UP*0.5 + LEFT*0.66, UP*0.5 + RIGHT*0.66, UP*0.5 + RIGHT*2]
        out_pos = [DOWN*1.5 + LEFT*1, DOWN*1.5 + RIGHT*1]

        # Create neurons as tiny dots first
        in_dots = VGroup(*[Dot(p, radius=0.05, color=BLUE) for p in in_pos])
        hid_dots = VGroup(*[Dot(p, radius=0.05, color=GRAY) for p in hid_pos])
        out_dots = VGroup(*[Dot(p, radius=0.05, color=GREEN) for p in out_pos])

        self.play(*[FadeIn(d) for d in [*in_dots, *hid_dots, *out_dots]], run_time=0.8)

        # Grow dots into pulsing circles
        in_circles = VGroup(*[Circle(radius=0.25, color=BLUE, fill_opacity=0.8).move_to(p) for p in in_pos])
        hid_circles = VGroup(*[Circle(radius=0.25, color=GRAY, fill_opacity=0.8).move_to(p) for p in hid_pos])
        out_circles = VGroup(*[Circle(radius=0.25, color=GREEN, fill_opacity=0.8).move_to(p) for p in out_pos])

        self.play(
            *[Transform(d, c) for d, c in zip([*in_dots, *hid_dots, *out_dots],
                                              [*in_circles, *hid_circles, *out_circles])],
            run_time=1
        )

        # Gentle pulse
        for _ in range(2):
            self.play(
                *[c.animate.scale(1.1) for c in [*in_circles, *hid_circles, *out_circles]],
                rate_func=there_and_back,
                run_time=0.6
            )

        # Draw directed edges
        edges = VGroup()
        for in_c in in_circles:
            for hid_c in hid_circles:
                edges.add(Arrow(in_c.get_center(), hid_c.get_center(), buff=0.25, stroke_width=1.5, color=WHITE))
        for hid_c in hid_circles:
            for out_c in out_circles:
                edges.add(Arrow(hid_c.get_center(), out_c.get_center(), buff=0.25, stroke_width=1.5, color=WHITE))

        self.play(*[Create(e) for e in edges], lag_ratio=0.05, run_time=1.5)

        # Group everything and zoom out
        full = VGroup(in_circles, hid_circles, out_circles, edges)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.play(full.animate.scale(0.6), run_time=3)
        self.wait(2)
