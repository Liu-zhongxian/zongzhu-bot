// 宗主后端启动器，由 tools/autostart.sh 编译进 ~/Applications/ZongzhuBackend.app。
//
// launchd 直接启动 bash 时，macOS 不弹授权窗口，读“桌面”“文稿”等目录会被静默拒绝。
// 以应用身份启动，再由它启动 start.sh，系统就会弹窗询问是否允许“宗主后端”访问。
//
// 用法：zongzhu-backend <仓库目录>。运行 <仓库目录>/start.sh，并用 caffeinate
// 防止 Mac 在后端运行期间空闲睡眠；收到退出信号时转给后端，后端退出后跟着退出。
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t backend = -1;

static void forward(int sig) {
    if (backend > 0) kill(backend, sig);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s REPO_DIR\n", argv[0]);
        return 2;
    }
    char script[PATH_MAX];
    if (snprintf(script, sizeof script, "%s/start.sh", argv[1]) >= (int)sizeof script) {
        fprintf(stderr, "path too long\n");
        return 2;
    }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);

    char *backend_args[] = {"/bin/bash", script, NULL};
    if (posix_spawn(&backend, backend_args[0], NULL, NULL, backend_args, environ) != 0) {
        perror("start.sh");
        return 1;
    }
    // caffeinate -w 在后端进程退出时自己结束。
    char pid[16];
    snprintf(pid, sizeof pid, "%d", backend);
    char *awake_args[] = {"/usr/bin/caffeinate", "-i", "-w", pid, NULL};
    pid_t awake;
    if (posix_spawn(&awake, awake_args[0], NULL, NULL, awake_args, environ) != 0) {
        perror("caffeinate");
    }

    int status;
    while (waitpid(backend, &status, 0) < 0) {
        if (errno != EINTR) {
            perror("waitpid");
            return 1;
        }
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
}
