#include <stdio.h>
int main(void) {
    int a, b;
    int *p = NULL;
    scanf("%d %d", &a, &b);
    *p = a + b;
    printf("%d\n", *p);
    return 0;
}
