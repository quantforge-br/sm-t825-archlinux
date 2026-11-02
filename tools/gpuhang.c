/* gpuhang: hang the GPU on purpose and see who survives the recovery.
 *
 * One draw whose fragment shader never ends (i += 2 never matches an odd
 * count).  The msm driver detects the hang, resets the GPU and blames this
 * process, which then reads GL_GUILTY_CONTEXT_RESET.  Other GL clients, the
 * compositor first of all, should keep running.  With kernel r12 and older
 * Hyprland 0.57 aborts at the first hang; with r13 (patch 0201) it keeps
 * running, unless the GPU hangs again right after the recovery and one of
 * Hyprland's own submits gets the blame.
 *
 * Build on the tablet: cc -O2 -Wall -o gpuhang gpuhang.c -lEGL -lGLESv2
 * Run:                 ./gpuhang          (or ./gpuhang 2000 for a short draw)
 * Then:                sudo dmesg | grep -E 'hangcheck|offending' | tail
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#ifndef GL_GUILTY_CONTEXT_RESET
#define GL_GUILTY_CONTEXT_RESET 0x8253
#endif

static GLuint sh(GLenum t, const char *src)
{
	GLuint s = glCreateShader(t);
	GLint ok;
	glShaderSource(s, 1, &src, NULL);
	glCompileShader(s);
	glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
	if (!ok) { char log[1024]; glGetShaderInfoLog(s, sizeof log, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(1); }
	return s;
}

int main(int argc, char **argv)
{
	/* an odd count never matches i (always even): the loop never ends */
	int iters = argc > 1 ? atoi(argv[1]) : 1;
	PFNEGLGETPLATFORMDISPLAYEXTPROC gpd = (void *)eglGetProcAddress("eglGetPlatformDisplayEXT");
	EGLDisplay d = gpd(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
	if (!eglInitialize(d, NULL, NULL)) { fprintf(stderr, "eglInitialize failed\n"); return 1; }
	eglBindAPI(EGL_OPENGL_ES_API);
	EGLint cattr[] = { EGL_CONTEXT_MAJOR_VERSION, 3,
		EGL_CONTEXT_OPENGL_RESET_NOTIFICATION_STRATEGY_EXT, EGL_LOSE_CONTEXT_ON_RESET_EXT, EGL_NONE };
	EGLContext c = eglCreateContext(d, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, cattr);
	if (c == EGL_NO_CONTEXT || !eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, c)) { fprintf(stderr, "context failed 0x%x\n", eglGetError()); return 1; }
	printf("renderer: %s\n", glGetString(GL_RENDERER));

	GLuint tex, fbo;
	glGenTextures(1, &tex); glBindTexture(GL_TEXTURE_2D, tex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 256, 256, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
	glGenFramebuffers(1, &fbo); glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
	glViewport(0, 0, 256, 256);

	const char *vs = "#version 300 es\nvoid main(){ vec2 p = vec2(float((gl_VertexID<<1)&2), float(gl_VertexID&2)); gl_Position = vec4(p*2.0-1.0, 0.0, 1.0); }\n";
	const char *fs = "#version 300 es\nprecision highp float; uniform int n; uniform float seed; out vec4 o;\n"
		"void main(){ float a = seed + gl_FragCoord.x; int i = 0; while (i != n) { a = fract(sin(a * 12.9898 + float(i)) * 43758.5453); i += 2; } o = vec4(a, 0.0, 0.0, 1.0); }\n";
	GLuint p = glCreateProgram();
	glAttachShader(p, sh(GL_VERTEX_SHADER, vs)); glAttachShader(p, sh(GL_FRAGMENT_SHADER, fs));
	glLinkProgram(p); glUseProgram(p);
	glUniform1i(glGetUniformLocation(p, "n"), iters);
	glUniform1f(glGetUniformLocation(p, "seed"), 0.5f);
	GLuint vao; glGenVertexArrays(1, &vao); glBindVertexArray(vao);

	printf("fbo status 0x%x, err 0x%x\n", glCheckFramebufferStatus(GL_FRAMEBUFFER), glGetError());
	struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
	printf("drawing with %d iterations per fragment\n", iters); fflush(stdout);
	glDrawArrays(GL_TRIANGLES, 0, 3);
	glFinish();
	clock_gettime(CLOCK_MONOTONIC, &t1);
	unsigned char px[4] = {0}; glReadPixels(7, 7, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
	printf("elapsed %.3f s, pixel %u,%u,%u,%u, err 0x%x\n", (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9, px[0], px[1], px[2], px[3], glGetError());
	GLenum (*grs)(void) = (GLenum (*)(void))eglGetProcAddress("glGetGraphicsResetStatusEXT");
	GLenum st = grs ? grs() : 0;
	printf("glFinish returned, reset status 0x%x%s\n", st, st == GL_GUILTY_CONTEXT_RESET ? " (GUILTY)" : "");
	return 0;
}
