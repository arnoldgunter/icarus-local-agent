# Allowed Read-Only Commands

Only commands listed in this file may be executed by the agent after user approval.
The backend parses fenced `bash` code blocks and uses the first word of each line as an allowed command.

Rules enforced by the backend:

- Commands must be read-only.
- Commands may be chained with `&&`, `||`, `;`, and pipes.
- Redirection and command substitution are blocked.
- All accessed absolute paths must stay inside the user's home directory or the configured upload directory.
- Destructive commands are blocked even if accidentally listed here.

```bash
ls
pwd
find
stat
file
cat
head
tail
wc
du
df
grep
egrep
fgrep
rg
awk
sed
sort
uniq
cut
tr
printf
echo
uname
whoami
id
date
uptime
free
ps
top
htop
lscpu
lsblk
mount
python
python3
jq
md5sum
sha1sum
sha256sum
```
