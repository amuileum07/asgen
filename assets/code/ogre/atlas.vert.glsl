#version 330 core

in vec4 vertex;
in vec3 normal;
in vec4 colour;
in vec2 uv0;
uniform mat4 uWorld;
uniform mat4 uNormal;
uniform mat4 uViewProj;
uniform vec3 uEye;
uniform vec4 uViewport;
uniform vec4 uMotion;    // time, wind X, wind Z, water level delta
uniform vec4 uPress[8];  // x, z, radius, recovery weight
uniform int uEffect;
uniform float uOutline;
out vec3 worldPosition;
out vec3 worldNormal;
out vec4 tint;
out vec2 uv;

void main() {
    vec4 p = uWorld * vertex;
    vec3 n = normalize(mat3(uNormal) * normal);
    if (uEffect >= 1 && uEffect <= 3) {
        float rootWeight = clamp(uv0.y, 0.0, 1.0);
        float phase = dot(p.xz, vec2(.113, .079));
        float pulse = sin(uMotion.x * 1.83 + phase) * .13
                    + sin(uMotion.x * 3.65 - phase * 1.72) * .042;
        float flexibility = uEffect == 2 ? .73 : 1.0;
        p.xz += (uMotion.yz * (.06 + pulse)) * rootWeight * flexibility;
        if (uEffect == 1) {
            p.y -= smoothstep(62.0, 172.0, length(uEye.xz-p.xz)) * rootWeight * .89;
            for (int i = 0; i < 8; ++i) {
                vec2 delta = p.xz - uPress[i].xy;
                float d = length(delta);
                float weight = (1.0 - smoothstep(.04, max(.10, uPress[i].z), d))
                             * uPress[i].w * rootWeight;
                p.y -= .24 * weight;
                p.xz += delta / max(.10, d) * weight * .22;
            }
        }
    } else if (uEffect == 4 || uEffect == 6) {
        p.y += uMotion.w + .029 * sin((p.x + p.z) * .68 + uMotion.x * 1.9);
    }
    worldPosition = p.xyz;
    worldNormal = n;
    tint = colour;
    uv = uv0;
    gl_Position = uViewProj * p;
    if (uOutline > 0.0) {
        vec4 tip = uViewProj * (p + vec4(n, 0.0));
        vec2 screen = tip.xy / max(.01, tip.w)
                    - gl_Position.xy / max(.01, gl_Position.w);
        float distance = max(.001, length(screen));
        gl_Position.xy += screen / distance * uViewport.zw
                       * (2.0 * uOutline) * gl_Position.w;
    }
}
