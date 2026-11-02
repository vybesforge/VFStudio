#!/bin/bash
# generates the vfrobot tiny dataset with FLUX.2 klein
cd /Users/dcruse/media-stack
D=train/datasets/vfrobot
mkdir -p $D
i=0
while IFS='|' read -r view bg; do
  i=$((i+1))
  f=$(printf "%s/vfrobot_%02d.png" $D $i)
  [ -f "$f" ] && continue
  out=$(gen image "a rusty orange toy robot with one glowing blue eye, boxy tin body, $view, $bg, studio photo, sharp focus" --model klein --seed $i --w 768 --h 768)
  echo "$out"
  src=$(echo "$out" | python3 -c 'import sys,json; d=json.loads(sys.stdin.readline()); print(d["files"][0] if d.get("ok") else "")')
  [ -n "$src" ] && cp "$src" "$f" && echo "vfrobot, a rusty orange toy robot with one glowing blue eye, boxy tin body, $view, $bg" > "${f%.png}.txt"
done <<'LIST'
three-quarter view|plain white background
front view|plain grey background
side profile view|wooden table background
rear three-quarter view|dark background
low angle view|pastel blue background
high angle view looking down|concrete floor background
close-up of the head|soft bokeh background
standing on a shelf|warm indoor light background
sitting on grass|outdoor garden background
walking pose, dynamic|neutral studio background
LIST
echo DATASET_DONE
