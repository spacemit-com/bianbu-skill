#!/bin/bash -e

# Version: 0.8
#   1. 更新不同模式下的测试参数
# Version: 0.7.1
#   1. 修复loop模式下的缺陷
# Version: 0.7.0
#   1. 支持K3
#   2. 优化脚本代码
# Version: 0.6.0
#   1. 修复Linux 6.6 fio运行出错的问题
#   2. 支持-k参数，终止测试
# Version: 0.5.0
#   1. 支持Bianbu Linux
#   2. 在当前终端启动测试
# Version: 0.4.0
#   1. 支持stress-ng
#   2. 支持chromium
# Version: 0.3.0
#   1. 支持自动下载视频
#   2. 支持自动更新
#   3. 支持iperf3静默安装
# Version: 0.2.0

CHECK=false
LOOP=false
KILL=false

while getopts "clkvh" opt
do
    case $opt in
        c)
            CHECK=true
            ;;
        l)
            LOOP=true
            ;;
        k)
            KILL=true
            ;;
        v)
            echo "0.8"
            exit 0
            ;;
        h)
            echo
            echo "Usage: $0"
            echo
            echo "Option:"
            echo "    -l Loop test"
            echo "    -k Kill all tests"
            echo
            exit 0
            ;;
        \?)
            exit 1
            ;;
    esac
done

if head /proc/cpuinfo | grep -i 'Spacemit(R) X60' > /dev/null
then
    CHIP=K1
elif head /proc/cpuinfo | grep -i 'Spacemit(R) X100' > /dev/null
then
    CHIP=K3
else
    echo "Unsupport chip"
    exit 1
fi

BL=false
DESKTOP=false
if grep -E "Bianbu Linux|Buildroot" /etc/issue > /dev/null
then
    BL=true
    HOME=/root
    XDG_VIDEOS_DIR=/root
    export XDG_RUNTIME_DIR=/root
    export WAYLAND_DISPLAY=wayland-1
    export MESA_LOADER_DRIVER_OVERRIDE=pvr
elif [ -f $HOME/.config/user-dirs.dirs ]
then
    DESKTOP=true
    . $HOME/.config/user-dirs.dirs
else
    echo "Running on no desktop environment"
fi

LOG_DIR=$HOME/logs/$(date +%Y%m%d%H%M%S)

# CPU测试参数
STRESS_ENABLE=true
# 循环测试：true | false，设为false时无间隔运行
STRESS_LOOP=false
STRESS_CPU=4
STRESS_CPU_LOAD=50
STRESS_TIME=86400
# 每次测试间隔，loop模式下有效，单位：秒
STRESS_DURATION=60
STRESS_LOG=$LOG_DIR/stress-ng.log

# DDR测试参数（memtester）
MEMTESTER_ENABLE=true
# 线程数
MEMTESTER_THREAD=2
MEMTESTER_SIZE=1G
# 循环测试：true | false，设为false时无间隔运行
MEMTESTER_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
MEMTESTER_DURATION=60
# 测试次数
MEMTESTER_ITERATIONS=1000
MEMTESTER_LOG=$LOG_DIR/memtester.log

# DDR测试参数（stressapptest）
STRESSAPPTEST_ENABLE=false
# 测试内存大小（MB），取系统总内存的 1/8
STRESSAPPTEST_MBYTES=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 8 ))
# memory copy 线程数
STRESSAPPTEST_THREADS=4
# 测试时间，单位：秒
STRESSAPPTEST_TIME=86400
# 循环测试：true | false，设为false时无间隔运行
STRESSAPPTEST_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
STRESSAPPTEST_DURATION=60
STRESSAPPTEST_LOG=$LOG_DIR/stressapptest.log

# GPU测试参数
GLMARK_ENABLE=true
GLMARK_CMD=glmark2-es2-wayland
# 循环测试：true | false，设为false时一直运行
GLMARK_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
GLMARK_DURATION=60
GLMARK_LOG=$LOG_DIR/glmark.log

# VPU解码测试参数
PLAYER_ENABLE=true
VIDEO_FILENAME=$XDG_VIDEOS_DIR/Roast_Duck_H.265_2160p_14m.mp4
VIDEO_CODEC=hevc_stcodec
# 循环测试：true | false，设为false时运行只一次就退出
PLAYER_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
PLAYER_DURATION=60
PLAYER_LOG=$LOG_DIR/player.log

# main storage、sdcard、UDisk
# 循环测试：true | false，设为false时运行只一次就退出
FIO_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
FIO_DURATION=60
# 每次测试时间，单位：秒
FIO_RUNTIME=86400
FIO_MAIN_ENABLE=true
# 测试文件名，通常无需修改
FIO_MAIN_FILENAME=$HOME/testfile.bin
# 测试文件大小
FIO_MAIN_FILESIZE=1G
FIO_MAIN_RUNTIME=$FIO_RUNTIME
FIO_MAIN_LOG=$LOG_DIR/fio-main.log
FIO_SDCARD_ENABLE=true
# sdcard测试文件名
FIO_SDCARD_FILENAME=/media/bianbu/sdcard/testfile.bin
# sdcard测试文件大小
FIO_SDCARD_FILESIZE=1G
FIO_SDCARD_RUNTIME=$FIO_RUNTIME
FIO_SDCARD_LOG=$LOG_DIR/fio-sdcard.log
FIO_UDISK_ENABLE=true
# U-Disk测试文件名
FIO_UDISK_FILENAME=/media/bianbu/udisk/testfile.bin
# U-Disk测试文件大小
FIO_UDISK_FILESIZE=1G
FIO_UDISK_RUNTIME=$FIO_RUNTIME
FIO_UDISK_LOG=$LOG_DIR/fio-udisk.log

# 网络测试参数
# 循环测试：true | false，设为false时运行只一次就退出
IPERF3_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
IPERF3_DURATION=60
# 每次测试时间，单位：秒
IPERF3_TIME=86400
IPERF3_SERVER1=10.0.91.40
IPERF3_PORT1=5201
IPERF3_END0=false
IPERF3_END0_IP=10.0.91.25
IPERF3_END0_TIME=$IPERF3_TIME
IPERF3_END0_LOG=$LOG_DIR/iperf3_end0.log
IPERF3_SERVER2=10.0.90.237
IPERF3_PORT2=5201
IPERF3_END1=false
IPERF3_END1_IP=10.0.90.55
IPERF3_END1_TIME=$IPERF3_TIME
IPERF3_END1_LOG=$LOG_DIR/iperf3_end1.log
IPERF3_SERVER3=10.0.90.237
IPERF3_PORT3=5201
IPERF3_WLAN0=false
IPERF3_WLAN0_IP=10.0.91.95
IPERF3_WLAN0_TIME=$IPERF3_TIME
IPERF3_WLAN0_LOG=$LOG_DIR/iperf3_wlan0.log

# chromium
CHROMIUM_ENABLE=true
if command -v chromium > /dev/null
then
    CHROMIUM_CMD=chromium
elif command -v chromium-browser > /dev/null
then
    CHROMIUM_CMD=chromium-browser
else
    CHROMIUM_ENABLE=false
fi
CHROMIUM_URL=https://www.bilibili.com/bangumi/play/ss33626
CHROMIUM_LOG=$LOG_DIR/chromium.log

# object dection
OBJECT_ENABLE=true
OBJECT_LOG=$LOG_DIR/object.log

# USB camera snapshot (K3 only)
SNAPSHOT_ENABLE=true
# 循环测试：true | false，设为false时运行只一次就退出
SNAPSHOT_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
SNAPSHOT_DURATION=60
SNAPSHOT_LOG=$LOG_DIR/snapshot.log

# CSI camera test (K3 only)
CSI_CAM_ENABLE=true
# 循环测试：true | false，设为false时运行只一次就退出
CSI_CAM_LOOP=false
# 每次测试间隔，loop模式下有效，单位：秒
CSI_CAM_DURATION=60
CSI_CAM_LOG=$LOG_DIR/csi-cam.log

# YOLOv8目标检测测试 (K3 only)
YOLOV8_ENABLE=false
YOLOV8_DIR=$HOME/yolo-test
YOLOV8_TIME=86400
YOLOV8_LOOP_COUNT=3000
YOLOV8_LOG=$LOG_DIR/yolov8.log

# llama
LLAMA_ENABLE=true
LLAMA_MODEL=Qwen3-0.6B-BF16_Q4.gguf
LLAMA_SERVER_LOG=$LOG_DIR/llama-server.log
LLAMA_TEST_LOG=$LOG_DIR/llama-test.log
LLAMA_TEST_SCRIPT=/tmp/llama-test.sh
LLAMA_TEST_CMD="curl -s http://localhost:8080/v1/chat/completions"
LLAMA_TEST_DURATION=1

if [ $CHECK = true ]
then
    log_dir=$(ls -td $HOME/logs/* | head -1)
    memtester_log=$log_dir/memtester.log
    echo "Checking latest log in $log_dir"
    for ((i=0; i<$MEMTESTER_THREAD; i++))
    do
        if [ -f $memtester_log.$i ]
        then
            if grep -Eiq "fail|error|fault" $memtester_log.$i
            then
                echo "memtester encounter error"
            fi
        fi
    done
    summary_script=/etc/cron.daily/daily-summary.sh
    if [ -x $summary_script ]
    then
        echo "Summarizing journal, it may take a few minutes"
        $summary_script
    fi
    exit 0
fi

RUNNING_STAMP=/tmp/.stability-test-running
cleanup()
{
    set +e
    pkill -9 -f stress-ng
    pkill -9 -f memtester
    pkill -9 -f stressapptest
    pkill -9 -f glmark2-es2
    pkill -9 -f mpv
    pkill -9 -f fio
    pkill -9 -f iperf3
    pkill -9 -f chromium
    pkill -9 -f PreviewThread
    pkill -9 -f snapshot
    pkill -9 -f csi-test
    pkill -9 -f yolov8
    pkill -9 -f "$LLAMA_TEST_SCRIPT"
    pkill -9 -f "$LLAMA_TEST_CMD"
    pkill -9 llama-server
    rm -f $RUNNING_STAMP
    exit 0
}
trap cleanup SIGINT

if [ $KILL = true ]
then
    cleanup
fi

if [ -f $RUNNING_STAMP ]
then
    echo "stability test is running"
    exit 0
fi

if [ $LOOP = true ]
then
    STRESS_LOOP=true
    STRESS_TIME=3600
    MEMTESTER_LOOP=true
    STRESSAPPTEST_LOOP=true
    GLMARK_ENABLE=true
    FIO_LOOP=true
    FIO_RUNTIME=3600
    IPERF3_LOOP=true
    IPERF3_TIME=3600
    SNAPSHOT_LOOP=true
    CSI_CAM_LOOP=true
    YOLOV8_TIME=3600
fi

if [ $CHIP = "K1" ]
then
    echo "Disable llama test for $CHIP"
    LLAMA_ENABLE=false
    SNAPSHOT_ENABLE=false
    CSI_CAM_ENABLE=false
    YOLOV8_ENABLE=false
elif [ $CHIP = "K3" ]
then
    echo "Disable object detection test for $CHIP"
    OBJECT_ENABLE=false
fi

if [ $BL = true ]
then
    # OBJECT_ENABLE=false
    CHROMIUM_ENABLE=false
elif [ $DESKTOP = false ]
then
    echo "Disable player, chromium test due to no desktop environment"
    PLAYER_ENABLE=false
    CHROMIUM_ENABLE=false
    GLMARK_CMD="glmark2-es2-drm --off-screen"
fi

mem_gib=$(awk '/^MemTotal:/ {printf "%.0f", $2/1024/1024}' /proc/meminfo)
if [ "$mem_gib" -le 4 ]
then
    echo "System memory is less than 4 GiB, adjust test parameters for low memory system"
    if [ $MEMTESTER_ENABLE = true ]
    then
        MEMTESTER_SIZE=100M
        echo "Fixed memtester size to $MEMTESTER_SIZE"
    fi
    if [ $STRESSAPPTEST_ENABLE = true ]
    then
        STRESSAPPTEST_MBYTES=128
        echo "Fixed stressapptest mbytes to $STRESSAPPTEST_MBYTES"
    fi

    if [ $PLAYER_ENABLE = true ]
    then
        VIDEO_FILENAME=$XDG_VIDEOS_DIR/C005_1080P_AVC_MPEG_10M_30F.avi
        VIDEO_CODEC=h264_stcodec
        echo "Use lower resolution video: $VIDEO_FILENAME"
    fi
fi

SETUP_STAMP=/var/local/stability-test-setup-done
if [ $BL = false -a ! -f $SETUP_STAMP ]
then
    echo "Setup environment for stability-test"
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
        htop \
        glances \
        btop \
        stress-ng \
        memtester \
        stressapptest \
        python3-spacemit-ort \
        libeigen3-dev \
        spacemit-onnxruntime \
        opencv-spacemit \
        glmark2-es2-wayland \
        glmark2-es2-drm \
        fio \
        iperf3 \
        curl
    if apt-cache search llama.cpp-tools-spacemit | grep -q llama.cpp-tools-spacemit
    then
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y llama.cpp-tools-spacemit
    else
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y llama-server
    fi
    if [ $CHIP = "K3" ]
    then
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y k3x-cam
    fi
    sudo touch $SETUP_STAMP
fi

mkdir -p $LOG_DIR

run()
{
    echo "run $*"
    bash -c "$* &"
}

loop_run()
{
    local cmd="$1 && sleep $2"

    echo "loop run $cmd"
    bash -c "while true; do $cmd; done &"
}

run_fio_test()
{
    local name=$1
    local filename=$2
    local filesize=$3
    local runtime=$4
    local logfile=$5
    local loop=$6
    local duration=$7

    if [ "$loop" = true ]
    then
        loop_run "fio -filename=$filename -name=$name -rw=randrw -rwmixread=50 -ioengine=libaio -direct=1 -bs=16k -numjobs=2 -iodepth=20 -size=$filesize -runtime=$runtime -time_based -group_reporting >> $logfile 2>&1" $duration
    else
        run "fio -filename=$filename -name=$name -rw=randrw -rwmixread=50 -ioengine=libaio -direct=1 -bs=16k -numjobs=2 -iodepth=20 -size=$filesize -runtime=$runtime -time_based -group_reporting >> $logfile 2>&1"
    fi
}

run_iperf3_test()
{
    local server=$1
    local port=$2
    local bind_ip=$3
    local time=$4
    local logfile=$5
    local loop=$6
    local duration=$7

    if [ "$loop" = true ]
    then
        loop_run "iperf3 -c $server -p $port -B $bind_ip --bidir -P 8 -t $time >> $logfile 2>&1" $duration
    else
        run "iperf3 -c $server -p $port -B $bind_ip --bidir -P 8 -t $time >> $logfile 2>&1"
    fi
}

if [ $STRESS_ENABLE = true ]
then
    echo "Run CPU test..."
    if [ $STRESS_LOOP = true ]
    then
        loop_run "stress-ng --cpu $STRESS_CPU --cpu-load $STRESS_CPU_LOAD --timeout $STRESS_TIME >> $STRESS_LOG 2>&1" $STRESS_DURATION
    else
        run "stress-ng --cpu $STRESS_CPU --cpu-load $STRESS_CPU_LOAD --timeout $STRESS_TIME >> $STRESS_LOG 2>&1"
    fi
fi

if [ $MEMTESTER_ENABLE = true ]
then
    echo "Run DDR test (memtester)..."
    for ((i=0; i<$MEMTESTER_THREAD; i++))
    do
        if [ $MEMTESTER_LOOP = true ]
        then
            loop_run "memtester $MEMTESTER_SIZE 1 >> $MEMTESTER_LOG.$i 2>&1" $MEMTESTER_DURATION
        else
            run "memtester $MEMTESTER_SIZE $MEMTESTER_ITERATIONS >> $MEMTESTER_LOG.$i 2>&1"
        fi
    done
fi

if [ $STRESSAPPTEST_ENABLE = true ]
then
    echo "Run DDR test (stressapptest)..."
    if [ $STRESSAPPTEST_LOOP = true ]
    then
        loop_run "stressapptest -s $STRESSAPPTEST_TIME -M $STRESSAPPTEST_MBYTES -C $STRESSAPPTEST_THREADS -m $STRESSAPPTEST_THREADS -i $STRESSAPPTEST_THREADS -W --stop_on_errors -l $STRESSAPPTEST_LOG > /dev/null 2>&1" $STRESSAPPTEST_DURATION
    else
        run "stressapptest -s $STRESSAPPTEST_TIME -M $STRESSAPPTEST_MBYTES -C $STRESSAPPTEST_THREADS -m $STRESSAPPTEST_THREADS -i $STRESSAPPTEST_THREADS -W --stop_on_errors -l $STRESSAPPTEST_LOG > /dev/null 2>&1"
    fi
fi

if [ $GLMARK_ENABLE = true ]
then
    echo "Run GPU test..."
    if [ $GLMARK_LOOP = true ]
    then
        loop_run "$GLMARK_CMD >> $GLMARK_LOG 2>&1" $GLMARK_DURATION
    else
        run "$GLMARK_CMD --run-forever >> $GLMARK_LOG 2>&1"
    fi
fi

if [ $PLAYER_ENABLE = true ]
then
    echo "Run VPU test..."
    [ -f $VIDEO_FILENAME ] || wget -q http://nexus.bianbu.xyz/repository/video/demo/`basename $VIDEO_FILENAME` -O $VIDEO_FILENAME
    if [ -f $VIDEO_FILENAME ]
    then
        if [ $BL = true ]
        then
            run "ffplay -codec:v $VIDEO_CODEC -ar 48000 -i $VIDEO_FILENAME -loop 10000 >> $PLAYER_LOG 2>&1"
        else
            if [ $PLAYER_LOOP = true ]
            then
                loop_run "mpv $VIDEO_FILENAME >> $PLAYER_LOG 2>&1" $PLAYER_DURATION
            else
                run "mpv --loop $VIDEO_FILENAME >> $PLAYER_LOG 2>&1"
            fi
        fi
    fi
fi

if [ $FIO_MAIN_ENABLE = true ]
then
    echo "Run main storage test..."
    run_fio_test "main" "$FIO_MAIN_FILENAME" "$FIO_MAIN_FILESIZE" "$FIO_MAIN_RUNTIME" "$FIO_MAIN_LOG" "$FIO_LOOP" "$FIO_DURATION"
fi

if [ $FIO_SDCARD_ENABLE = true ] && [ -d `dirname $FIO_SDCARD_FILENAME` ]
then
    echo "Run sdcard test..."
    run_fio_test "sdcard" "$FIO_SDCARD_FILENAME" "$FIO_SDCARD_FILESIZE" "$FIO_SDCARD_RUNTIME" "$FIO_SDCARD_LOG" "$FIO_LOOP" "$FIO_DURATION"
fi

if [ $FIO_UDISK_ENABLE = true ] && [ -d `dirname $FIO_UDISK_FILENAME` ]
then
    echo "Run U-Disk test..."
    run_fio_test "U-Disk" "$FIO_UDISK_FILENAME" "$FIO_UDISK_FILESIZE" "$FIO_UDISK_RUNTIME" "$FIO_UDISK_LOG" "$FIO_LOOP" "$FIO_DURATION"
fi

if [ $IPERF3_END0 = true ]
then
    echo "Run end0 iperf3 test..."
    run_iperf3_test "$IPERF3_SERVER1" "$IPERF3_PORT1" "$IPERF3_END0_IP" "$IPERF3_END0_TIME" "$IPERF3_END0_LOG" "$IPERF3_LOOP" "$IPERF3_DURATION"
fi

if [ $IPERF3_END1 = true ]
then
    echo "Run end1 iperf3 test..."
    run_iperf3_test "$IPERF3_SERVER2" "$IPERF3_PORT2" "$IPERF3_END1_IP" "$IPERF3_END1_TIME" "$IPERF3_END1_LOG" "$IPERF3_LOOP" "$IPERF3_DURATION"
fi

if [ $IPERF3_WLAN0 = true ]
then
    echo "Run wlan0 iperf3 test..."
    run_iperf3_test "$IPERF3_SERVER3" "$IPERF3_PORT3" "$IPERF3_WLAN0_IP" "$IPERF3_WLAN0_TIME" "$IPERF3_WLAN0_LOG" "$IPERF3_LOOP" "$IPERF3_DURATION"
fi

if [ $CHROMIUM_ENABLE = true ]
then
    echo "Run chromium browser test..."
    run "$CHROMIUM_CMD $CHROMIUM_URL >> $CHROMIUM_LOG 2>&1"
fi

if [ $OBJECT_ENABLE = true ]
then
    echo "Run object detection test..."
    run "detection_stream_demo /usr/share/ai-support/models/yolov6.json 0 >> $OBJECT_LOG 2>&1"
fi

if [ $SNAPSHOT_ENABLE = true ]
then
    echo "Run USB camera snapshot test..."
    if [ $SNAPSHOT_LOOP = true ]
    then
        loop_run "snapshot >> $SNAPSHOT_LOG 2>&1" $SNAPSHOT_DURATION
    else
        run "snapshot >> $SNAPSHOT_LOG 2>&1"
    fi
fi

if [ $CSI_CAM_ENABLE = true ]
then
    echo "Run CSI camera test..."
    if [ $CSI_CAM_LOOP = true ]
    then
        loop_run "csi-test -n 0 -c 0 -a 1 >> $CSI_CAM_LOG 2>&1" $CSI_CAM_DURATION
        loop_run "csi-test -n 1 -c 2 -a 1 >> $CSI_CAM_LOG 2>&1" $CSI_CAM_DURATION
    else
        run "csi-test -n 0 -c 0 -a 1 >> $CSI_CAM_LOG 2>&1"
        run "csi-test -n 1 -c 2 -a 1 >> $CSI_CAM_LOG 2>&1"
    fi
fi

if [ $YOLOV8_ENABLE = true ]
then
    echo "Run YOLOv8 test..."
    if [ ! -f $YOLOV8_DIR/yolov8 ]
    then
        echo "Downloading YOLOv8 test resources..."
        wget -q https://nexus.bianbu.xyz/repository/test-resources/k3-yolov8-test.tar.gz -O /tmp/k3-yolov8-test.tar.gz
        mkdir -p $YOLOV8_DIR
        tar -xzf /tmp/k3-yolov8-test.tar.gz -C $YOLOV8_DIR
        rm -f /tmp/k3-yolov8-test.tar.gz
    fi
    if [ -f $YOLOV8_DIR/yolov8 ]
    then
        echo "Clearing TCM before YOLOv8..."
        spacemit-tcm-smi -c
        run "cd $YOLOV8_DIR && end=\$((SECONDS+$YOLOV8_TIME)); while [ \$SECONDS -lt \$end ]; do ./yolov8 ./yolov8.yaml --model-path ./yolov8m.q.onnx --image ./bus.jpg --loop-count $YOLOV8_LOOP_COUNT >> $YOLOV8_LOG 2>&1; done"
    fi
fi

if [ $LLAMA_ENABLE = true ]
then
    echo "Run llama test..."
    [ -f $LLAMA_MODEL ] || wget -q http://nexus.bianbu.xyz/repository/ModelZoo/gguf/qwen3/`basename $LLAMA_MODEL` -O $LLAMA_MODEL
    if [ -f $LLAMA_MODEL ]
    then
        echo "Clearing TCM before llama..."
        spacemit-tcm-smi -c
        llama_ctx=2048
        if [ "$(awk '/^MemTotal:/ {printf "%d", $2/1024/1024}' /proc/meminfo)" -gt 8 ]; then
            llama_ctx=4096
        fi
        run "llama-server -c $llama_ctx -m ./Qwen3-0.6B-BF16_Q4.gguf -t 8 > $LLAMA_SERVER_LOG 2>&1"
        printf "Waiting for llama-server ready"
        while true
        do
            sleep 1
            if grep "listening on http://127.0.0.1:8080" $LLAMA_SERVER_LOG > /dev/null
            then
                break
            fi
            printf "."
        done
        printf "\n"
        cat > $LLAMA_TEST_SCRIPT << EOF
$LLAMA_TEST_CMD \
  -H "Content-Type: application/json" \
  -d '{
       "messages": [
         {"role": "system", "content": "您是一个资深旅游博主"},
         {"role": "user", "content": " 请为我介绍一下美丽的中国"}
       ]
      }' >> $LLAMA_TEST_LOG 2>&1
echo >> $LLAMA_TEST_LOG
echo --- >> $LLAMA_TEST_LOG
EOF
        loop_run "bash $LLAMA_TEST_SCRIPT" $LLAMA_TEST_DURATION
    fi
fi

echo "All tests started, log at: $LOG_DIR"
touch $RUNNING_STAMP
