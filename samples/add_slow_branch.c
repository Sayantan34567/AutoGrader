#include <stdio.h>

static long long add(long long x, long long y) {
    return x + y;
}

int main(void) {
    long long x, y;
    if (scanf("%lld %lld", &x, &y) != 2) return 1;
    if (x > 2000000000LL) {              /* input-dependent slow path */
        for (volatile long i = 0; i < 20000000000L; i++) { }
    }
    printf("%lld\n", add(x, y));
    return 0;
}
