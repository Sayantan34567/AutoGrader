#include <stdio.h>

/* Adds two integers using a 64-bit type so INT_MAX + 1 cannot overflow. */
static long long add(long long lhs, long long rhs) {
    return lhs + rhs;
}

int main(void) {
    long long lhs = 0;
    long long rhs = 0;

    /* Read both numbers from one line of input. */
    if (scanf("%lld %lld", &lhs, &rhs) != 2) {
        return 1;
    }
    printf("%lld\n", add(lhs, rhs));
    return 0;
}
