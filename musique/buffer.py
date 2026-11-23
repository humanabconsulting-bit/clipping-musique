"""Publication via Buffer (API GraphQL officielle, clé personnelle BUFFER_API_KEY).

- `python -m musique.buffer canaux` : vérifie la clé et liste les organisations / chaînes (lecture seule).
- `programmer(...)` : programme une vidéo (lien public) sur une chaîne Buffer à une date précise.
Docs : https://developers.buffer.com
"""
from __future__ import annotations

import os
import sys

import requests

API = "https://api.buffer.com"
CLE = "BUFFER_API_KEY_MUSIQUE"  # nom du secret utilisé (un compte Buffer par secret)


def gql(query: str, variables: dict | None = None) -> dict:
    cle = os.environ.get(CLE, "")
    if not cle:
        raise RuntimeError(f"clé Buffer absente (secret GitHub {CLE})")
    r = requests.post(API, json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"}, timeout=60)
    if r.status_code == 429:
        raise RuntimeError(f"Buffer : trop de requêtes, réessayer après {r.headers.get('Retry-After', '?')} s")
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(f"Buffer : {j['errors'][0].get('message')}")
    return j["data"]


def organisations() -> list[dict]:
    return gql("query { account { organizations { id name } } }")["account"]["organizations"]


def canaux(org_id: str) -> list[dict]:
    q = """query C($organizationId: OrganizationId!) {
      channels(input: { organizationId: $organizationId }) { id name service }
    }"""
    return gql(q, {"organizationId": org_id})["channels"]


def programmer(channel_id: str, service: str, texte: str, video_url: str, quand_iso: str | None,
               titre: str | None = None) -> str:
    """Programme une vidéo. Retourne l'id du post Buffer (ou lève une erreur)."""
    meta = {}
    if service == "youtube":
        meta = {"youtube": {"title": (titre or texte)[:100], "categoryId": "20", "madeForKids": False,
                            "privacy": "public", "notifySubscribers": True}}
    elif service == "tiktok":
        meta = {"tiktok": {"isAiGenerated": False}}
    q = """mutation P($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id dueAt } }
        ... on MutationError { message }
      }
    }"""
    entree = {"channelId": channel_id, "text": texte, "schedulingType": "automatic", "mode": "customScheduled",
              "dueAt": quand_iso, "assets": [{"video": {"url": video_url}}]}
    if quand_iso is None:  # publier tout de suite
        entree["mode"] = "shareNow"
        entree.pop("dueAt")
    if meta:
        entree["metadata"] = meta
    res = gql(q, {"input": entree})["createPost"]
    if not res.get("post"):
        raise RuntimeError(f"Buffer a refusé le post : {res.get('message')}")
    return res["post"]["id"]


def supprimer(post_id: str) -> None:
    q = """mutation D($input: DeletePostInput!) { deletePost(input: $input) {
      __typename ... on VoidMutationError { message } } }"""
    res = gql(q, {"input": {"id": post_id}})["deletePost"]
    if res.get("message"):
        raise RuntimeError(f"Buffer : {res['message']}")


def limites(channel_ids: list[str], date_iso: str) -> list[dict]:
    q = """query L($input: DailyPostingLimitsInput!) { dailyPostingLimits(input: $input) {
      channelId isAtLimit limit scheduled sent } }"""
    return gql(q, {"input": {"channelIds": channel_ids, "date": date_iso}})["dailyPostingLimits"]


def posts(org_id: str, channel_ids: list[str]) -> list[dict]:
    q = """query P($input: PostsInput!) { posts(input: $input) { edges { node {
      id status dueAt sentAt externalLink channelId text error { message } } } } }"""
    inp = {"organizationId": org_id, "filter": {"channelIds": channel_ids},
           "sort": [{"field": "dueAt", "direction": "desc"}]}
    return [e["node"] for e in gql(q, {"input": inp})["posts"]["edges"]]


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--cle":
        CLE = sys.argv[2]
        del sys.argv[1:3]
    if sys.argv[1:2] == ["posts"]:
        for o in organisations():
            for c in canaux(o["id"]):
                for p in posts(o["id"], [c["id"]]):
                    err = (p.get("error") or {}).get("message", "")
                    print(f"POST {c['service']:<8} {p['status']:<10} prévu {p.get('dueAt')} envoyé {p.get('sentAt')} "
                          f"{p.get('externalLink') or ''} {err} | {(p.get('text') or '')[:50]}")
    if sys.argv[1:2] == ["supprimer"]:
        for pid in sys.argv[2:]:
            supprimer(pid)
            print(f"supprimé : {pid}")
    if sys.argv[1:2] == ["limites"]:
        for o in organisations():
            ids = [c["id"] for c in canaux(o["id"])]
            for date in sys.argv[2:] or [None]:
                for l in limites(ids, date) if date else gql("""query L($input: DailyPostingLimitsInput!) {
                        dailyPostingLimits(input: $input) { channelId isAtLimit limit scheduled sent } }""",
                        {"input": {"channelIds": ids}})["dailyPostingLimits"]:
                    print(f"LIMITE {date or 'aujourdhui'} {l}")
    if sys.argv[1:] == ["canaux"]:
        for o in organisations():
            print(f"ORGANISATION {o['name']} — id {o['id']}")
            for c in canaux(o["id"]):
                print(f"   CHAINE {c['service']:<10} {c['name']:<30} id {c['id']}")
