from manim import *

class Scene4(Scene):
    def construct(self):
        # Softmax matrix on the left
        softmax_labels = ["cat", "sat", "on", "down"]
        softmax_matrix = VGroup(*[
            VGroup(*[
                Text("0.25" if i == j else "0.08", font_size=24, color=YELLOW)
                for j in range(4)
            ]).arrange(RIGHT, buff=0.4)
            for i in range(4)
        ]).arrange(DOWN, buff=0.3).to_edge(LEFT, buff=1)
        softmax_title = Text("Softmax", font_size=24).next_to(softmax_matrix, UP, buff=0.2)
        self.add(softmax_matrix, softmax_title)

        # Value vectors on the right
        value_vecs = VGroup(*[
            Rectangle(height=2, width=0.4, color=BLUE, fill_opacity=0.8)
            for _ in range(4)
        ]).arrange(DOWN, buff=0.4).to_edge(RIGHT, buff=1)
        value_labels = VGroup(*[
            Text(f"V_{{{tok}}}", font_size=24).next_to(vec, RIGHT, buff=0.1)
            for tok, vec in zip(softmax_labels, value_vecs)
        ])
        values_title = Text("Value vectors", font_size=24).next_to(value_vecs, UP, buff=0.2)
        self.add(value_vecs, value_labels, values_title)

        # Output placeholder vectors on the left of center
        output_vecs = VGroup(*[
            Rectangle(height=2, width=0.4, color=GREEN, fill_opacity=0.8)
            for _ in range(4)
        ]).arrange(DOWN, buff=0.4).shift(LEFT * 2)
        output_labels = VGroup(*[
            Text(f"Output_{{{tok}}}", font_size=24).next_to(vec, LEFT, buff=0.1)
            for tok, vec in zip(softmax_labels, output_vecs)
        ])
        self.add(output_vecs, output_labels)

        # Animate attention for each token
        for row_idx in range(4):
            # Highlight matrix row
            row = softmax_matrix[row_idx]
            self.play(row.animate.set_color(ORANGE), run_time=0.3)

            # Create weight beams
            beams = VGroup()
            for col_idx in range(4):
                weight = 0.25 if row_idx == col_idx else 0.08
                beam = Line(
                    start=row[col_idx].get_right(),
                    end=value_vecs[col_idx].get_left(),
                    stroke_width=2,
                    color=YELLOW
                )
                beam.scale(weight * 2)  # visual scaling
                beams.add(beam)
            self.play(Create(beams), run_time=0.4)

            # Scale value vectors
            scaled_vecs = VGroup()
            for col_idx in range(4):
                weight = 0.25 if row_idx == col_idx else 0.08
                scaled = value_vecs[col_idx].copy()
                scaled.stretch(weight, 0, about_edge=LEFT)
                scaled_vecs.add(scaled)
            self.play(*[TransformFromCopy(value_vecs[i], scaled_vecs[i]) for i in range(4)], run_time=0.4)

            # Slide scaled vectors to center and sum
            sum_vec = Rectangle(height=2, width=0.4, color=GREEN, fill_opacity=0.8).move_to(output_vecs[row_idx])
            self.play(
                *[scaled_vecs[i].animate.move_to(sum_vec.get_center()).scale(0) for i in range(4)],
                Transform(output_vecs[row_idx], sum_vec),
                run_time=0.5
            )
            self.play(FadeOut(beams), FadeOut(scaled_vecs), run_time=0.2)
            self.play(row.animate.set_color(YELLOW), run_time=0.2)

        # Slide new outputs left to replace embeddings
        original_embeddings = VGroup(*[
            Rectangle(height=2, width=0.4, color=GRAY, fill_opacity=0.5)
            for _ in range(4)
        ]).arrange(DOWN, buff=0.4).next_to(softmax_matrix, RIGHT, buff=1)
        self.add(original_embeddings)
        self.play(
            output_vecs.animate.move_to(original_embeddings.get_center()),
            FadeOut(original_embeddings),
            run_time=0.8
        )
        self.wait(0.5)