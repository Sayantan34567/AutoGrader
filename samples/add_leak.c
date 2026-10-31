#include <stdio.h>
#include <stdlib.h>

static long long add(long long x, long long y) {
    return x + y;
}

int main(void) {
    long long *result = malloc(sizeof *result);   /* never freed */
    long long x, y;
    if (scanf("%lld %lld", &x, &y) != 2) return 1;
    *result = add(x, y);
    printf("%lld\n", *result);
    return 0;
}
