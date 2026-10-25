"""The skill and AI this project had before the gateway."""
from core.gateway.agents.grok_webhook import GrokWebhookAgent
from core.gateway.skills.music import MusicSkill

SKILLS = [MusicSkill()]
AGENTS = [GrokWebhookAgent()]
