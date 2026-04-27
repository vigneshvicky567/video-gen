from manim import *

class Scene3(Scene):
    def construct(self):
        # Constants for triangle legs and hypotenuse
        a = 3
        b = 4
        c = np.sqrt(a**2 + b**2) # This will be 5
        side_length = a + b # This will be 7

        # Colors for visualization
        square_color = BLUE_D
        triangle_colors = [RED_E, GREEN_E, YELLOW_E, PURPLE_E]
        highlight_color = YELLOW
        label_color = WHITE

        # --- Part 1: First Large Square (Left Side) ---
        # Create the large square on the left
        large_square_left = Square(side_length=side_length, color=square_color, fill_opacity=0.2)
        large_square_left.to_edge(LEFT, buff=1)
        self.play(Create(large_square_left))
        self.wait(0.5)

        # Define the bottom-left corner of the large square as a reference point
        bl_left = large_square_left.get_corner(DL)

        # Create the four identical right-angled triangles for the first arrangement (c^2 in center)
        # Triangle 1 (bottom-left corner)
        t1_left = Polygon(
            bl_left,
            bl_left + a * RIGHT,
            bl_left + b * UP,
            color=triangle_colors[0], fill_opacity=0.8, stroke_width=2
        )

        # Triangle 2 (bottom-right corner)
        t2_left = Polygon(
            bl_left + a * RIGHT,
            bl_left + side_length * RIGHT,
            bl_left + side_length * RIGHT + a * UP - b * UP, # Adjusted for correct orientation
            color=triangle_colors[1], fill_opacity=0.8, stroke_width=2
        )
        # Corrected points for t2_left: (a,0), (a+b,0), (a+b,a) -> (a,0), (a+b,0), (a+b,a) is wrong
        # It should be (a,0), (a+b,0), (a+b,a) rotated 90 deg CW
        # The points are: (side_length/2, -side_length/2), (side_length/2, -side_length/2 + a), (side_length/2 - b, -side_length/2)
        # Relative to bl_left:
        t2_left = Polygon(
            bl_left + side_length * RIGHT,
            bl_left + side_length * RIGHT + a * UP,
            bl_left + (side_length - b) * RIGHT,
            color=triangle_colors[1], fill_opacity=0.8, stroke_width=2
        )

        # Triangle 3 (top-right corner)
        t3_left = Polygon(
            bl_left + side_length * RIGHT + side_length * UP,
            bl_left + (side_length - a) * RIGHT + side_length * UP,
            bl_left + side_length * RIGHT + (side_length - b) * UP,
            color=triangle_colors[2], fill_opacity=0.8, stroke_width=2
        )

        # Triangle 4 (top-left corner)
        t4_left = Polygon(
            bl_left + side_length * UP,
            bl_left + side_length * UP + b * RIGHT,
            bl_left + (side_length - a) * UP,
            color=triangle_colors[3], fill_opacity=0.8, stroke_width=2
        )

        triangles_left_final = VGroup(t1_left, t2_left, t3_left, t4_left)

        # Central square (c^2)
        c_square_left = Square(side_length=c, color=highlight_color, fill_opacity=0.5, stroke_width=3)
        c_square_left.move_to(large_square_left.get_center())
        c_square_label = MathTex("c^2", color=label_color).scale(1.5)
        c_square_label.move_to(c_square_left.get_center())

        # Initial positions for animation (off-screen)
        triangles_left_initial = VGroup()
        triangles_left_initial.add(t1_left.copy().shift(DL * 5))
        triangles_left_initial.add(t2_left.copy().shift(DR * 5))
        triangles_left_initial.add(t3_left.copy().shift(UR * 5))
        triangles_left_initial.add(t4_left.copy().shift(UL * 5))

        self.play(
            LaggedStart(*[TransformFromCopy(triangles_left_initial[i], triangles_left_final[i]) for i in range(4)], lag_ratio=0.2),
            run_time=2
        )
        self.play(
            Create(c_square_left),
            Write(c_square_label)
        )
        self.wait(1)

        # --- Part 2: Second Large Square (Right Side) ---
        # Create the second large square on the right
        large_square_right = Square(side_length=side_length, color=square_color, fill_opacity=0.2)
        large_square_right.to_edge(RIGHT, buff=1)
        self.play(Create(large_square_right))
        self.wait(0.5)

        # Define the bottom-left corner of the large square as a reference point
        bl_right = large_square_right.get_corner(DL)

        # Create the four identical right-angled triangles for the second arrangement (a^2 and b^2)
        # These triangles form two rectangles, leaving two squares.

        # Rectangle 1 (bottom-right): filled by t1_right and t2_right
        # t1_right: (a,0), (a+b,0), (a,b) relative to bl_right
        t1_right = Polygon(
            bl_right + a * RIGHT,
            bl_right + side_length * RIGHT,
            bl_right + a * RIGHT + b * UP,
            color=triangle_colors[0], fill_opacity=0.8, stroke_width=2
        )
        # t2_right: (a+b,0), (a+b,b), (a,b) relative to bl_right
        t2_right = Polygon(
            bl_right + side_length * RIGHT,
            bl_right + side_length * RIGHT + b * UP,
            bl_right + a * RIGHT + b * UP,
            color=triangle_colors[1], fill_opacity=0.8, stroke_width=2
        )

        # Rectangle 2 (top-left): filled by t3_right and t4_right
        # t3_right: (0,a), (b,a), (0,a+b) relative to bl_right
        t3_right = Polygon(
            bl_right + a * UP,
            bl_right + b * RIGHT + a * UP,
            bl_right + side_length * UP,
            color=triangle_colors[2], fill_opacity=0.8, stroke_width=2
        )
        # t4_right: (b,a), (b,a+b), (0,a+b) relative to bl_right
        t4_right = Polygon(
            bl_right + b * RIGHT + a * UP,
            bl_right + b * RIGHT + side_length * UP,
            bl_right + side_length * UP,
            color=triangle_colors[3], fill_opacity=0.8, stroke_width=2
        )

        triangles_right_final = VGroup(t1_right, t2_right, t3_right, t4_right)

        # Squares a^2 and b^2
        a_square_right = Square(side_length=a, color=highlight_color, fill_opacity=0.5, stroke_width=3)
        a_square_right.move_to(bl_right + a/2 * RIGHT + a/2 * UP) # Bottom-left square
        a_square_label = MathTex("a^2", color=label_color).scale(1.5)
        a_square_label.move_to(a_square_right.get_center())

        b_square_right = Square(side_length=b, color=highlight_color, fill_opacity=0.5, stroke_width=3)
        b_square_right.move_to(bl_right + (a + b/2) * RIGHT + (a + b/2) * UP) # Top-right square
        b_square_label = MathTex("b^2", color=label_color).scale(1.5)
        b_square_label.move_to(b_square_right.get_center())

        # Initial positions for animation (off-screen)
        triangles_right_initial = VGroup()
        triangles_right_initial.add(t1_right.copy().shift(DR * 5))
        triangles_right_initial.add(t2_right.copy().shift(DR * 5))
        triangles_right_initial.add(t3_right.copy().shift(UL * 5))
        triangles_right_initial.add(t4_right.copy().shift(UL * 5))

        self.play(
            LaggedStart(*[TransformFromCopy(triangles_right_initial[i], triangles_right_final[i]) for i in range(4)], lag_ratio=0.2),
            run_time=2
        )
        self.play(
            Create(a_square_right),
            Write(a_square_label),
            Create(b_square_right),
            Write(b_square_label)
        )
        self.wait(1)

        # --- Part 3: Conclusion ---
        # Fade out the four triangles from both arrangements
        self.play(
            FadeOut(triangles_left_final),
            FadeOut(triangles_right_final)
        )
        self.wait(0.5)

        # Group the remaining elements for final positioning
        final_left_group = VGroup(large_square_left, c_square_left, c_square_label)
        final_right_group = VGroup(large_square_right, a_square_right, a_square_label, b_square_right, b_square_label)

        # Shift the groups closer to the center
        self.play(
            final_left_group.animate.shift(RIGHT * 1.5),
            final_right_group.animate.shift(LEFT * 1.5)
        )

        # Add the equality sign
        equality_sign = MathTex("=", color=label_color).scale(3)
        equality_sign.move_to(ORIGIN) # Position between the two groups
        self.play(Write(equality_sign))
        self.wait(2)

        # Final fade out of all elements
        self.play(
            FadeOut(final_left_group),
            FadeOut(final_right_group),
            FadeOut(equality_sign)
        )
        self.wait(1)