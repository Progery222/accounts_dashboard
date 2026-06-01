import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from accounts.models import Account, Platform, Post

username = "theylla.zen"
acc = Account.objects.filter(platform=Platform.THREADS, username__iexact=username).first()
if not acc:
    acc = Account.objects.filter(platform=Platform.THREADS, username__icontains="theylla").first()
if not acc:
    print("NOT_FOUND", file=sys.stderr)
    sys.exit(2)
posts = list(Post.objects.filter(account=acc).order_by("-posted_at"))
print(f"id={acc.id} user={acc.username} name={acc.display_name!r}")
print(f"followers={acc.follower_count} post_count={acc.post_count} db_posts={len(posts)}")
for p in posts[:5]:
    print(f"  {p.external_id} v={p.view_count} l={p.like_count} c={p.comment_count}")
if len(posts) > 5:
    print(f"  ... +{len(posts)-5} more")
