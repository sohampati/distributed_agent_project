# Trusted helper that creates and destroys each task's fixed-size disk (ext4 image on a loop device).
# It runs privileged (attaching loop devices needs it) but only ever executes fixed commands built by the worker,
# never task input. The agent sandbox itself stays unprivileged.
FROM alpine:3.20
RUN apk add --no-cache e2fsprogs e2fsprogs-extra losetup
