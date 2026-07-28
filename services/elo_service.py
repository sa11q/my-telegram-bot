class EloService:
    def __init__(self, k_factor: int = 32):
        self.k_factor = k_factor

    def expected_score(self, rating_a: int, rating_b: int) -> float:
        return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

    def calculate_new_ratings(self, rating_a: int, rating_b: int, score_a: float) -> tuple[int, int]:
        exp_a = self.expected_score(rating_a, rating_b)
        exp_b = self.expected_score(rating_b, rating_a)
        
        new_rating_a = rating_a + self.k_factor * (score_a - exp_a)
        new_rating_b = rating_b + self.k_factor * ((1 - score_a) - exp_b)
        
        return int(round(new_rating_a)), int(round(new_rating_b))
