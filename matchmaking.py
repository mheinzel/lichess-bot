import random
import time
import logging

logger = logging.getLogger(__name__)


class Matchmaking:
    def __init__(self, li, config, username):
        self.li = li
        self.username = username
        self.variants = list(filter(lambda variant: variant != "fromPosition", config["challenge"]["variants"]))

        matchmaking_cfg = config.get("matchmaking") or {}
        challenge_cfgs = matchmaking_cfg.get("challenges") or [{}]

        self.allow_matchmaking = matchmaking_cfg.get("allow_matchmaking") or False
        self.challenge_timeout = matchmaking_cfg.get("challenge_timeout") or 30

        self.cfgs = []
        for cfg in challenge_cfgs:
            # Use defaults from top level, but override
            self.cfgs.append({**matchmaking_cfg, **cfg})

        self.last_challenge_created = time.time()
        self.last_game_ended = time.time()
        self.challenge_expire_time = 25  # The challenge expires 20 seconds after creating it.
        self.challenge_id = None

    def should_create_challenge(self):
        time_has_passed = self.last_game_ended + (self.challenge_timeout * 60) < time.time()
        challenge_expired = self.last_challenge_created + self.challenge_expire_time < time.time() and self.challenge_id
        # Wait 20 seconds before creating a new challenge to avoid hitting the api rate limits.
        twenty_seconds_passed = self.last_challenge_created + 20 < time.time()
        if challenge_expired:
            self.li.cancel(self.challenge_id)
            logger.debug(f"Challenge id {self.challenge_id} cancelled.")
        return self.allow_matchmaking and (time_has_passed or challenge_expired) and twenty_seconds_passed

    def create_challenge(self, username, base_time, increment, days, variant, mode):
        rated = mode == "rated"
        params = {"rated": rated, "variant": variant}
        if days:
            params["days"] = days
        else:
            params["clock.limit"] = base_time
            params["clock.increment"] = increment
        challenge_id = self.li.challenge(username, params).get("challenge", {}).get("id")
        return challenge_id

    def choose_opponent(self, cfg):
        mode = cfg.get("challenge_mode") or "random"
        if mode == "random":
            mode = random.choice(["casual", "rated"])

        variant = cfg.get("challenge_variant") or "random"
        if variant == "random":
            variant = random.choice(self.variants)

        base_time = cfg.get("challenge_initial_time", 60)
        increment = cfg.get("challenge_increment", 2)
        days = cfg.get("challenge_days")
        game_duration = base_time + increment * 40
        if variant != "standard":
            game_type = variant
        elif days:
            game_type = "correspondence"
        elif game_duration < 179:
            game_type = "bullet"
        elif game_duration < 479:
            game_type = "blitz"
        elif game_duration < 1499:
            game_type = "rapid"
        else:
            game_type = "classical"

        min_rating = cfg.get("opponent_min_rating") or 600
        max_rating = cfg.get("opponent_max_rating") or 4000

        online_bots = self.li.get_online_bots()
        online_bots = list(filter(lambda bot: bot["username"] != self.username and not bot.get("disabled") and
                                  min_rating <= ((bot["perfs"].get(game_type) or {}).get("rating") or 0) <= max_rating,
                                  online_bots))
        bot_username = random.choice(online_bots)["username"] if online_bots else None
        return bot_username, base_time, increment, days, variant, mode

    def challenge(self):
        cfg = random.choice(self.cfgs)
        bot_username, base_time, increment, days, variant, mode = self.choose_opponent(cfg)
        challenge_info = cfg.get("challenge_name") or variant
        logger.info(f"Will challenge {bot_username} for a game ({challenge_info}).")
        challenge_id = self.create_challenge(bot_username, base_time, increment, days, variant, mode) if bot_username else None
        logger.info(f"Challenge id is {challenge_id}.")
        self.last_challenge_created = time.time()
        self.challenge_id = challenge_id
