#version 330 core

in vec3 worldPosition;
in vec3 worldNormal;
in vec4 tint;
in vec2 uv;
out vec4 fragment;
uniform vec3 uEye;
uniform vec3 uSun;
uniform vec4 uBase;
uniform vec4 uAtmosphere; // daylight, fog, snow, wet
uniform vec4 uCliff;      // fog base height, time, ice, dust
uniform vec4 uLine;
uniform int uEffect;
uniform int uPaint;
uniform int uRoof;
uniform int uTextured;
uniform sampler2D uTexture;
uniform vec4 uMarks[8];
uniform vec4 uLamps[8];

void main() {
    if (uEffect == 7) {
        fragment = tint;
        return;
    }
    vec3 n = normalize(worldNormal);
    vec3 view = normalize(uEye - worldPosition);
    vec3 albedo = uPaint != 0 ? tint.rgb : uBase.rgb;
    if (uTextured != 0) albedo *= texture(uTexture, uv).rgb;
    if (uRoof != 0 && n.y > .2) {
        vec2 tile = uv / vec2(.64, .4);
        tile.x += mod(floor(tile.y), 2.0) * .5;
        vec2 distanceToJoint = .5 - abs(fract(tile) - .5);
        vec2 edgeWidth = max(fwidth(tile), vec2(.008));
        vec2 joint = 1.0 - smoothstep(vec2(.012), vec2(.045) + edgeWidth, distanceToJoint);
        float variation = fract(sin(dot(floor(tile), vec2(29.87, 67.12))) * 287.69);
        float visible = 1.0 - smoothstep(.08, .40, max(edgeWidth.x, edgeWidth.y));
        albedo *= 1.0 + (.078*(variation-.5) - .14*max(joint.x, joint.y)) * visible;
    }
    float diffuse = max(0.0, dot(n, normalize(uSun)));
    vec3 shadow = vec3(.50, .60, .76);
    vec3 midtone = vec3(.78, .82, .84);
    vec3 highlight = vec3(1.0, .97, .86);
    bool foliage = uEffect == 1 || uEffect == 2;
    vec3 light = mix(shadow, midtone, smoothstep(.27, .33, diffuse));
    light = mix(light, highlight, smoothstep(.67, .73, diffuse));
    if (foliage) light = mix(shadow, highlight, smoothstep(.33, .54, diffuse));
    vec3 colour = albedo * light * uAtmosphere.x;
    float rim = pow(max(0.0, 1.0 - dot(n, view)), 3.0) * (1.0 - diffuse);
    colour += vec3(1.0, .85, .62) * rim * uAtmosphere.x * (foliage ? .026 : .062);
    float contact = foliage ? mix(.86, 1.0, smoothstep(0.0, .36, uv.y)) : 1.0;
    colour *= contact;
    float snow = uAtmosphere.z * smoothstep(.48, .94, n.y);
    if (!foliage && uEffect == 0) colour = mix(colour, vec3(.66, .78, .82)*light, snow*.84);
    float wet = uAtmosphere.w * max(0.0, n.y);
    colour *= 1.0 - wet * .14;
    colour += vec3(.74,.84,.93) * wet * .065 * pow(max(0.0, dot(n, view)), 8.0);
    if (uEffect == 0 && uPaint != 0 && n.y > .65 && snow + wet > .53) {
        float mark = 0.0;
        for (int i = 0; i < 8; ++i) {
            vec2 offset = (worldPosition.xz - uMarks[i].xy) * vec2(1.68, 1.0);
            mark = max(mark, (1.0 - smoothstep(.04, max(.06, uMarks[i].z * .30), length(offset))) * uMarks[i].w);
        }
        colour *= 1.0 - mark * (.21 + .13 * snow);
    }
    if (uEffect == 4 || uEffect == 6) {
        float ripple = sin(dot(worldPosition.xz, vec2(.89, .44)) + uCliff.y * 2.3);
        float gleam = pow(max(0.0, ripple), 15.0);
        colour = mix(vec3(.075,.28,.34),albedo,.61) * max(.30,uAtmosphere.x);
        colour += gleam * vec3(.21,.28,.29) * (.26+.74*rim);
        colour = mix(colour, vec3(.48,.67,.73), clamp(uCliff.z * 3.8, 0.0, .86));
    }
    if (uEffect == 5) colour = mix(colour, vec3(1.0,.61,.23), (1.0-uAtmosphere.x)*.88);
    for (int i = 0; i < 8; ++i) {
        if (uLamps[i].w <= 0.0) continue;
        vec3 delta = uLamps[i].xyz - worldPosition;
        float distanceToLamp = length(delta);
        float glow = 1.0 - smoothstep(.1, uLamps[i].w, distanceToLamp);
        float facing = .38 + .62 * max(0.0, dot(n, delta / max(.05, distanceToLamp)));
        colour += albedo * vec3(1.0,.64,.30) * glow * glow * facing * 1.67;
    }
    if (uLine.a > 0.0) colour = uLine.rgb * (.55 + .45*uAtmosphere.x);
    float distanceToEye = length(uEye - worldPosition);
    float air = 1.0 - exp(-.00060 * max(distanceToEye - 100.0, 0.0));
    float low = 1.0 - smoothstep(7.0,34.0,worldPosition.y-uCliff.x);
    float mist = uAtmosphere.y * (1.0-exp(-.034*distanceToEye)) * (.27+.73*low);
    vec3 horizon = mix(vec3(.58,.76,.81),vec3(.70,.57,.41),uCliff.w);
    horizon *= .47 + .53*uAtmosphere.x;
    fragment = vec4(mix(colour,horizon,1.0-(1.0-air)*(1.0-mist)),uBase.a);
}
