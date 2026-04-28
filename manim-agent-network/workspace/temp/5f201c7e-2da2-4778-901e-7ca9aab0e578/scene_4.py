from manim import *
import numpy as np

class Scene4(Scene):
    def construct(self):
        # Title
        title = Text("Learning = Tiny Nudges", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # 2-D loss surface (purple translucent mesh)
        axes = ThreeDAxes(
            x_range=[-3, 3, 1], y_range=[-3, 3, 1], z_range=[0, 6, 1],
            x_length=6, y_length=6, z_length=4
        ).shift(DOWN*0.5)

        def loss_surface(x, y):
            return 0.5 * (x**2 + y**2) + 0.5

        surface = Surface(
            lambda u, v: axes.c2p(u, v, loss_surface(u, v)),
            u_range=[-3, 3], v_range=[-3, 3],
            resolution=(20, 20),
            fill_color=PURPLE, fill_opacity=0.4,
            stroke_color=PURPLE, stroke_width=0.5
        )
        self.play(Create(axes), FadeIn(surface))
        self.wait(0.5)

        # Red dot sliding downhill
        start = np.array([2.5, 2.5, loss_surface(2.5, 2.5)])
        dot = Dot3D(axes.c2p(*start), color=RED, radius=0.08)
        self.play(FadeIn(dot))

        # Gradient path (simple straight line toward origin)
        steps = 20
        for i in range(1, steps + 1):
            t = i / steps
            x = 2.5 * (1 - t)
            y = 2.5 * (1 - t)
            z = loss_surface(x, y)
            self.play(dot.animate.move_to(axes.c2p(x, y, z)), run_time=0.1, rate_func=linear)
        self.wait(0.5)

        # Neural network diagram
        nn_group = VGroup()
        layers = [[0, 0], [1, 0], [2, 0]]
        neurons = []
        for layer_idx, layer in enumerate(layers):
            col = []
            for neuron_idx, y in enumerate(layer):
                neuron = Circle(radius=0.15, color=WHITE, stroke_width=2)
                neuron.move_to(axes.c2p(-3 + 2 * layer_idx, y - 1, 0))
                col.append(neuron)
                nn_group.add(neuron)
            neurons.append(col)

        # Arrows (weights)
        arrows = VGroup()
        for i in range(len(neurons) - 1):
            for src in neurons[i]:
                for dst in neurons[i + 1]:
                    arrow = Arrow(src.get_center(), dst.get_center(), buff=0.15, stroke_width=3)
                    arrows.add(arrow)
        nn_group.add(arrows)

        # Scale and position network
        nn_group.scale_to_fit_width(4)
        nn_group.move_to(RIGHT * 3.5 + DOWN * 0.5)
        self.play(FadeIn(nn_group))

        # Animate weights shrinking/stretching slightly
        for _ in range(5):
            for arrow in arrows:
                new_length = arrow.get_length() * (0.95 + 0.1 * np.random.rand())
                arrow.save_state()
                arrow.scale(new_length / arrow.get_length(), about_point=arrow.get_start())
            self.play(*[Restore(arrow) for arrow in arrows], run_time=0.4)

        self.wait(2)