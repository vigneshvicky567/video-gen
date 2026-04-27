from manim import *

class Scene1(Scene):
    def construct(self):
        # Set background color to white for a clean look
        self.camera.background_color = WHITE

        # 1. Coordinate grid fades in and out
        grid = NumberPlane(x_range=[-7, 7, 1], y_range=[-4, 4, 1],
                            background_line_style={"stroke_opacity": 0.2, "stroke_color": BLACK})
        self.play(FadeIn(grid, run_time=1))
        self.wait(0.5)
        self.play(FadeOut(grid, run_time=1))

        # Define vertices for the right triangle
        # Q is the right angle vertex
        Q = LEFT * 2 + DOWN * 2
        R = Q + RIGHT * 4
        P = Q + UP * 3

        # 2. Draw the right triangle
        triangle = Polygon(P, Q, R, color=BLUE, fill_opacity=0, stroke_width=4)
        self.play(Create(triangle))

        # Label vertices P, Q, R
        label_Q = MathTex("Q", color=BLACK).next_to(Q, DOWN + LEFT * 0.5)
        label_R = MathTex("R", color=BLACK).next_to(R, DOWN + RIGHT * 0.5)
        label_P = MathTex("P", color=BLACK).next_to(P, UP + LEFT * 0.5)
        self.play(FadeIn(label_P, label_Q, label_R))

        # Mark angle Q as 90 degrees with a square symbol
        right_angle_mark = RightAngle(triangle, Q, length=0.4, quadrant=(-1, -1), color=RED, stroke_width=5)
        self.play(FadeIn(right_angle_mark))

        # Label sides 'a', 'b', 'c'
        # Side QR is 'a'
        label_a = MathTex("a", color=BLACK).move_to(Line(Q, R).get_center()).shift(DOWN * 0.5)
        # Side PQ is 'b'
        label_b = MathTex("b", color=BLACK).move_to(Line(P, Q).get_center()).shift(LEFT * 0.5)
        # Hypotenuse PR is 'c'
        # Calculate a vector perpendicular to PR for label placement
        pr_vector = P - R
        perpendicular_vector = np.array([-pr_vector[1], pr_vector[0], 0]) # Rotate 90 deg counter-clockwise
        perpendicular_vector = perpendicular_vector / np.linalg.norm(perpendicular_vector) # Normalize
        label_c = MathTex("c", color=BLACK).move_to(Line(P, R).get_center() + perpendicular_vector * 0.5)

        self.play(GrowFromCenter(label_a), GrowFromCenter(label_b), GrowFromCenter(label_c))

        # Text 'Leg a', 'Leg b', 'Hypotenuse c' briefly appear and fade out
        text_leg_a = Text("Leg a", font_size=30, color=BLACK).next_to(label_a, DOWN)
        self.play(FadeIn(text_leg_a))
        self.wait(1)
        self.play(FadeOut(text_leg_a))

        text_leg_b = Text("Leg b", font_size=30, color=BLACK).next_to(label_b, LEFT)
        self.play(FadeIn(text_leg_b))
        self.wait(1)
        self.play(FadeOut(text_leg_b))

        # Adjust placement for 'Hypotenuse c' to be further out from the hypotenuse
        text_hyp_c = Text("Hypotenuse c", font_size=30, color=BLACK).move_to(label_c.get_center() + perpendicular_vector * 0.7)
        self.play(FadeIn(text_hyp_c))
        self.wait(1)
        self.play(FadeOut(text_hyp_c))

        self.wait(2)
