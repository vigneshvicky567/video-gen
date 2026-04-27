from manim import *

class Scene3(Scene):
    def construct(self):
        # Title
        title = Tex("Multi-Head", "Attention").arrange(DOWN, buff=0.1).to_edge(UP)
        self.play(Write(title))
        self.wait()

        # Single head
        head = Rectangle(width=1.5, height=0.9, color=WHITE)
        label = Tex("Head").scale(0.7).move_to(head.get_center())
        single = VGroup(head, label).move_to(ORIGIN)
        self.play(Create(single))
        self.wait()

        # 2×4 grid
        grid = VGroup()
        for i in range(8):
            r, c = divmod(i, 4)
            copy = single.copy().scale(0.5)
            copy.move_to(np.array([c - 1.5, 0.5 - r, 0]) * 1.2)
            grid.add(copy)
        self.play(Transform(single, grid[0]), *[FadeIn(g) for g in grid[1:]])
        self.remove(single)
        self.add(grid)
        self.wait()

        # Vectors
        arrows = VGroup()
        for g in grid:
            a = Arrow(g.get_right(), g.get_right() + 0.4 * RIGHT, color=PURPLE, buff=0)
            arrows.add(a)
        self.play(*[GrowArrow(a) for a in arrows])
        self.wait()

        # Concat bar
        bar = Rectangle(width=5, height=0.6, color=WHITE).next_to(grid, DOWN, buff=0.6)
        concat = Tex("Concatenate").scale(0.7).next_to(bar, DOWN)
        self.play(
            *[a.animate.scale(0.5).move_to(bar.get_left() + (0.3 + 0.55 * i) * RIGHT) for i, a in enumerate(arrows)],
            Create(bar),
            Write(concat)
        )
        self.wait()

        # Projection
        proj = Rectangle(width=1, height=2, color=TEAL, fill_opacity=0.3).next_to(bar, RIGHT, buff=1)
        w_o = MathTex(r"W_O").move_to(proj.get_center())
        proj_group = VGroup(proj, w_o).shift(LEFT * 6)
        self.play(proj_group.animate.shift(RIGHT * 6))
        self.wait()

        # Output
        out = Arrow(proj.get_right(), proj.get_right() + 1.2 * RIGHT, color=YELLOW, buff=0)
        mh = Tex("MH-Attn").scale(0.7).next_to(out, RIGHT)
        self.play(GrowArrow(out), Write(mh))
        self.wait()

        # Clean finale
        final = VGroup(out, mh).copy()
        full = VGroup(title, grid, arrows, bar, concat, proj_group, final)
        full.scale_to_fit_width(12).move_to(ORIGIN)
        self.play(
            FadeOut(grid),
            FadeOut(arrows),
            FadeOut(bar),
            FadeOut(concat),
            FadeOut(proj_group),
            final.animate.move_to(ORIGIN)
        )
        self.wait(2)