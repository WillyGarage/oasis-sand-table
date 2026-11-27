// The browser shapes the whole Thai word with its embedded font before we
// trace any strokes. In particular, an upper vowel and a tone mark can stack.
window.GuestThaiLettering = (() => {
  const family='Oasis Thai Looped', em=240;
/* Embedded font: Noto Sans Thai Looped, Regular.
Copyright 2022 The Noto Project Authors (https://github.com/notofonts/thai)
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------
PREAMBLE

The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font
creation efforts of academic and linguistic communities, and to provide
a free and open framework in which fonts may be shared and improved in
partnership with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded,
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply to
any document created using the fonts or their derivatives.

DEFINITIONS

"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components
as distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to,deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software
to a new environment.

"Author" refers to any designer, engineer, programmer, technical writer
or other person who contributed to the Font Software.

PERMISSION & CONDITIONS

Permission is hereby granted, free of charge, to any person obtaining a
copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components, in
Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or in
the appropriate machine-readable metadata fields within text or binary
files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the
corresponding Copyright Holder. This restriction only applies to the
primary font name as presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole, must
be distributed entirely under this license, and must not be distributed
under any other license. The requirement for fonts to remain under this
license does not apply to any document created using the Font Software.

TERMINATION

This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER

THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
*/
  const fontData='d09GMgABAAAAACvsABAAAAAAeWwAACuJAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGoEaG5IiHIwQBmA/U1RBVEQAgjARCAqBsgyBi3oLgi4AATYCJAOEWAQgBYUCB44XDAcbE2RVRoWNA0AEy9k5EmG3N6k6BP9/SpDjqOJvDfwAhAi6CSerUbKW5dXRAY2kIC3c7mrLxU4MHEZvZvLN54RKmKZEggCon8pX/OFV6cu+gwpXfKnL3pWhdLy0Jo6QZPZ42tbPvF1SXMIoBMRq9PzYgFGch5dNqNhxkVUfompZZtfse2oB/wfw4VNnmLNyLriYABEjAlCACQGx6wF+Wz4nHCImEfGC9ygVwSB9YNIieGHmdW+NV9Hb/r+q7SJ7kTwfHuz93fiA4wgSjwKTTIJwu/t/N/uZEtruTFhNgKpSUVgR5UQqa7TP9Ldfub/JL2ZrLiwNIEAA+FJvniN/4GsNz8O5Fv3fwibWQIU6j74KO4KbmrqCRYlWcX56PEqjg8Zmz/Y7Z1a7k/353zmF2VHlc648bfFzYgTkaf6yJgAUuPYx9+/bbE7vJHkppYA8/r7XsgJX5dKTl0lPTlOilChlThHcrXCgWuGIFCpCxUa1tqqShP1C2P/3Osv2214fcgUh9hWdHaAKuOOi/3q2Tvp/CeU9H7LXR6RVNLZkiH1EqEPuAoAlewOEh1hUW155KbqUSbcp03cpysDzNW065cmjSrPJKYkxaZtL+xP1Ka0JtQl0oVAYj2Mw3mNj2HaAUr+MyDF6f/bLrCDqzK21BAk8EDyQAKJx8tV2994OEMGA6mMnIDhQEqSlhdKkQV10gQYYABlNQZlmGoTYAHIBZALQIajWliIoRmwNYDYcGlef7oUAps4BRhgL1dhREw+LEIgCnwuAT28w1u5L3xEi7urKrRDxVG4sBMXbfpXFEPHV0i8fItAAwGZDASAoOujRWOf//gPbQMQbY3kxBE3UXFC+KzQTwV1QWeMBiRFF4t8yZ95a/1JX6nisURJhE0F8LDif4CPg3GACCvfddNlZxx2021brrbTVYnNNN9FoQzWrVc7KNM/WV3cduyPtvXNl0sE2Lghnp0pdo0/N34W4vaI2p9Tww0pmS33W21ojJIUYxRWF/z4uQhridRmonmHEpmLB7EPVcMV6xLQFszvVhUH+6FLrZQUx3s2r/AOCdioNzsbzNMWMlc+OQTdY6EvlLEQIW5e5c8S0GXLi9evQcbNpvYlHoEcIBB1zkdLgSyl/N+Cqjdi4AMD2RWM927t5PZ9w8oxx5it4+LYfTrN97+TR/xvBhxAAjYb47BBO3NFkvPCFCsWIEkMoUSIHGjkcGeRRIES4eNj47FAEBJAbdxQlJeQjAAoWAsWIQaipoTgJUKIkLBo6RJYshF5bHAZ56ICbRbC0MHzKItO/MkUm5J+Oot2VAZyKRhreu+mmyuEL1uJ96WRDK+mfbYCcvGoWAXsMDwpK0WKoJUqWIlWadBkydTINl77fa0toBwPy0AEd0en+KR79hao/GtjPsKnwpfR3qRbpyEDmdJaYvGgALXTIYiZe+YAWOiOLkQ1sEKYZZLEIfvgMLXTI4gLffEALHbI8BOBurES6AJcuFMFdJYhgJTHKmLQ0hha/7xgyEtZ0AtpqSk2qEo43RQZO5LdUR5UQ+JGi4D7dMUxpOQkJ/EUdf4eP8NpT3D/yZgrhmmv5rqOOq1OddX2dXK7l+CTDSliuzvtBIPNdw8jXZg2gxWnIrQn02Fzmxp6U6simQ2rENE5DsTow6L0GY7KZ8onDCZuRbj3XZ1zkRBIS0x96pTysl7C51Y0nuagHpqd0GdyUoLOSQiaiJE0OjLU1AgBstVifrOye8GLavlghzuN9o321+2WlLk6jQfrmcTm9glPqcQRmyD29zpPmNN6+WV3tzeaszfIszOxMzfiMzOA0Zmi60pK69E8k/pSkMNaY29OjE1ZaOyDKSOOMpaLwkb6u5X/4CZ/BFd4+yXMP3XbVeScdttd2G2u51fZayrf1fDNNNtbwWYZxBK7z7CmCNdr7B2B+caPSNAaNmS4bp4heEo8Gx/YQPgeYlKRUGSKjhrIpNFZjt95rG0w8DeQ1Atkry4AD9C6u+eJ+ahz56AynRkMCnCnyODahimkqFos/Ibfe6m096oD0Bpsu6VZkbi2LpxtP9eqYvm491cs4kRwvAi/mI5UrSZN9mTSeFgdB8Dm6rMuZMtZ1Anhj6r4OUXxQqjuzCDVSIzVS420U+qL3XloF6Pf03bhBwqFW3yDkRJur0gMTsXyUsnHoFdEVUUTyh67g/WG4d29rJQy8G1BUCp3flgywgqGgbEq9dtJna74Z1J+ry4tBBaCASEBiEhED4SwW2lTlsz6UPcn0m763z+79e/G27jTSe5HwcSyJBNSfhoYfv0xQk+BP5Jj8hehhbsE3HhP1vNFIlfpC4eZKfYTVT7aYvZnGG6peKZOe2suUJFoQhaimuYkpltaKtMItf8vXklsOltgSWnYWr8ARezwsFx9DRELGh58wETRSR6bYVtlcKB8AOZpFKWQvJ6K0cUGCs53Ww6NeSiQ4Sani2hYkQzlCAHbue1yzfFYlylWqUadeo2atYqvVkKTqN/H6gw0x1LAEWYLiXfhLy0DAolCxMuNUq9WgSYtBxjvaCyC+f2eu3BUoUqpClSkmmGiSyYuODiERX85z4sLNnMgEHXEc+LVsALwaGUMS4LT1xrLK5oqClAcI8FazmdWMhumHWwwFBUlyWpC4e75FnMUrE9aopVrXppBiwEoFR+JFowiAkG1JtifQEMMBT3HYMXiO29MRgtcLBwgSMmLi5oTZrLPNLCytdas0qDSptKgM0rHjx1qcfW0xDh47QmIO7ttezpe/cJEeOUsrzZMsKbgJ5apZiHZoLqh/31xECD6alDMRvsmIcSYhykxEFJuAKOTEcK/cMK/EUM9qiOaHBo9iLEsLmiGdhejUnAKgaXtjMC3C3AaTIh1wfQ0sdeRLncXmfRTNJzDOAdFRNSdEvR5FjY4x32EB8mt1BZDT/Snwkqp0gKywCM2iCaERGrfNOGiXAQeB71/68T0K3Ky81rsh2VynY8UoQ5NSAMfC8Ml+fCyViPVq7istmJA+lH5fSaqvgUlDSNjpRED+gJCpjsDcTemSgqriJPZ3BrCnsDB7142iqMhmM8oO6bhu19GOPTy+X5sNcF8JGQ7j3aGd3IaF+J8wVQfxvfesPGNO/5P5GQA+C3EA8Onv74Dbv6GGLdEoXV9ljWZx8c9KY0U+t9yDlOd5bLkXJe+UuzxAoKDznoamXz7hLe8umfmUF4ZZ4MR0hH7nrMrq3Czd1ASSDO4fr4te+ugNYdsIAQBMBwC4DfAEyOcBvC8AYDwAKwAAApEWZ8yUoNpKM5SqC3RlK2GJFGhGhyNEhPbFAsVtgw6hRmM9tW0igihPRSARLWhEJ/HVSABDKKTsX+swhA3RZNKE5y/iiphB1as2BYCeaMVTOsnjDLOMVciy9B3fongs0o9EVoRpy9momOhmLng/QyOrkVZXNeVqg9AUmkRLhfXy+hrZptBOG0JiIcjIAzTEvEI3xLd20roiXUY3Yh8lwAGYXwY8ktEZCSppdXy1pNWzXMnoprgtsicrrDDGMm2ljjoWGguRtFiWOvHt1AghB1hYyItKxEULmSwzwh5ZVjL+EtMN8hoW1LMwIuvzOGhrgbTYnSdJciOKO037jQYaqUTrHXTRyTKWWlIJUrsTExnrRbpl3qo81Z4qxZFVW55fLS20pREFQistJTLmTRtgt0ea8bhfRCjiLWigwGV2GohcApENwXq9+fl9AMaQKoRzgUwvg4F+R3aFomanhIv+8yoAOz10cYVV0JSuWHTJdsHyGLegUC4FzpXL1nmTCUo/SMebGF6qY7DU8/7TICvJ8pfRCfQDhWltWVIO+Bj+ZAbemXV2hqLdcBxcLgKYUujRsplySDdflICmo0mnRsbx53nrOYt+bN8e59GivEk2rN4bTamH0whdLNUek1MXXITZf2kdPWAo+2A8xZO97AwRheA71avjpRxdFqRpwwI2c2U097ZQidfY6zIuXf0fPPV4tZS4jpuqodEdUjjtlsxbw2IUTvjvuk71MijpRLgV7+EwWOLtMeX19/vd8jwjU2e+XrbnY3y2HYL46hsigwU3wo0QBAJIPnXQibfiyBJR/WXmshV0vF1t9sBxgLmsovdFaRWn9aPoYokerlKdLI4N7VusctwFb8GfQ7lz+/fQcQH8o7Xx3/bbycEU1d2N9cYohPEolwMMp6/fv/uC6oxpQVBaGpKMW1wmFfWTkDFS94JmH0CYkYTvG+mjZ/koysDVyKRvsH1d9kDxbmdUSh2GMIUFcgRPLtb3LJy4aVs2eD2lanI2ZxRkS1R5EXUgF6N/mYQwgzT9bLJuX4sGaZSPPtaj+k3LigXRb++eSVWr9Lv8F1RXSJxsNMyjsi/mFUX1hzKUo3TSFKa1dBRBmptIg4VJUA2QyUkwmTrVCmItIyaTj0EDRVzWPr1gZ9kF0RnZ55eYoivQS6X4m61ApRNaCquULYgKX/Lv7QRQd5arz2vPj7IA8Tbyab5HWxhhs6Qhz8UV2wEAXdd+08+JYeDcsK4janZ0sB0FJhuuPR2sNDdVucEJ2aeenzN4RYeb1JpvdLcDRDeqT39vR6oXd0LsSAy+MkmKny+6RZuGu2DEswtvkdFUcp/KDJI2hMEdPWDS63ODyAsBusyuTN8S6+fCtO4FHWarGMrC72BqG4/mPOjoBmeGkcnq1O3Sb9yuhK+0zrQsQpsAJ7afltgAQt53Y28/u5BzQ3aD7zPjlkriKM0ZI1tQvp6rcrOUwi5TwSOWxCmvI8YBWKo/Xto29/5maNPXGt3yfKJ9tVjP0zzJ+V3Ef46ptJyvpaSY9U9MgXjo0b336S5tJaFRPtBn1cL3EiiIZMnJZff03U8Wdw7ZSHYU367pIXyZMjgHrUowPrY4NUqCVTJD4ICQxF0f529ul+glkrlpd3sBkvsGj4SRqBe3sSIsx3d3pFGn2ORlu2JgV/nSz+cI1t0I475+VFtCv4wNJM3gvMJ3WkkwEOlZMKYV1WA4q8V3ylAO5w8NJ8an5fnMXH0vbuIsjC5gbOrb3T12ECHRJTKnFYzOV3NG/tTG/GqqZAV3ZsviQhy4hEN843Zhv+BI+k7nBuk7Bj9XJ4nchIZAFHptV3L1Osdm1Y4f1MSkHFSQETsstKZmnUdd+h6h1dxdmwMZ3MRFqA7inxVxT7ap0p8INUgFipgHDFOYbnFqxYf4E+qZCzZ2CVJOYW8S78fkwbSMgveGTsMhkn7JVFpTpoO70ihC1w9wm119blrHWThtnzvPrhimYaBB5f3K/8n+sGB8FDiu3etDwhoTM2P5cnDzVPudX6eDf3eZjB7NuMQms7+fkb56vYaYvA3OIp0nM6MPbgHYZ8mTk1guJ4TySb2S2Ual8YU7S/f94U5ZXg/KfadGwS0aGayTeQOF6u6ZvBMXcRP+d4+qUQHCQq670qf0a6ydIK3nDyxgO0W64CBbuRQJ04E4X2CLS6kKY4m5Z0lvUO9DWeJbB84ZzhXWnj2OL/pBnuOjGpQaFb+wYKUlfJ0l7D0KJhWKk45778VbS2jgwhr02ZvpmIH6hw6Eu/cp0dTjLSUfxzHOYtzK1G1cjCFb8RM8tMh4clN7dhIazYDbZG8ubsz5vI6mw56YdaMjNtrh5EKCwozAXbazxHlsHlANo4rthYCE2ZbtPeH4YideRiBh9NEU6ylN4UsLJJ7b0LOo5J/RwA+vPpUXjkKjA4czncpfiR3ZIkA+px42ORe+YWd7DQXtTQi1HCPgdCx8nhn/I6TOoRkhbdbQPGk/yp1uPVzAeFvT9z46eiAbWA2TNPXjq3lDkVOjbN3qAhedh5vR+W+uuI0l2UXRmoupxnaVph2hP7MhojQzJhqiAQJqffGKIx5pXeM9WnkCxdsa27broD36sCHy/YudgiZH3MHTBZAtgzedpdiKQHis3TjNvbfXNAK62aPp3WFJc7Nkum+2R7ZJzZMvJTBb11cc4QND/fkeqOJKExn+tWkUDDsUWORfNHPd3DCPmE8Zf2ZE5ZfL0tf5ohcZD2Xh93oqjDbt0DE849cDXrXSq+MiJHsDjATXn7cmcdBedJ4cbKlGK/Q0LH344woUGDm5ev08XLoeNJBBm+sY/gAIZ3Tap4aIeQdbyaMAAJycoBvKZZOVRs5dSZ1HWQmYeM21Q3sEEl6Vk4n41fiHTGVcAWvDZfootGvPjYf1LuopbHAp6BMSSqQuv5J2HweLIyDKAsX/UPhmhO5WG8xHEcVQKMzDKjccXmvi4ktpOVKRiuiIXgCXD+iirX7zB02DNd1A3QRjDgsH7axWd8W9no+b69LjrhJMOCAWCZ3jXsVwxTm/jpOgPTq7rnSWnVtfKP3/A7TdgzbqJY3ORndjWNAl4vg6Eni/o93k3L5DiXdHNBhROf2qrSIMiRuaRyzR+YJ3yg6yjV0I4ckcyutaKsTtRHrLss6U1PxBS47jazj+m6LCMOOJD96SfT3PKsNicDf3qloPIxfyns1oQsDLbBcRY47ZFVX7OeOvI8OchrcI8cPb5hkZKJOnxv4heN/zWtXgsxVddqSz92xiA6pFtiMnaGxEzf6Ypz7nuYjGCujLkQ+2VAsL1oOWM4EJJ4OcTShzK4SILD7nn+wN4qmeGnaRuc+kgfXi7U/IaUKOkG97ovhjRWPSqKUh72SEYvpu4b6WE6+Im6bjqn1w0wOwwdvnzrunC4h1KrcTyCvi4NvMW/+DRn1mXSYueNj4qoAwTpFqMYfaEM+QwY1NDdEGDHMWYX6bOU2/2hICxmh/wsUbX21kDhARfxZMI30t+1IOaQG4R5c5xMDc/5p2Clw4lR3m7o4e01P1d1cxGuj0BkbnMcY5jPBczpzTi/HQF1Lxf3uUiBcAdTCAKGUzi/86Vq7UWZSNyY+CXN2MWV9zZF0mdf1z2s+jzyjLKNd3jB81fNCY7o5wNFxaVuouCQdKSAwLxMLvgN2/KtFqEKjWKNhCxSkv92nwtMg19T4j/LwhQ3EVHlWi9VCiHciTRx1ZVyNWo2lwwrKS7DHRMfoPR0OefBxPe5WFuVTZX6dHhxaBlSD1rEBDJXA3Nivw3AVj/WKuvk8V2dbsqxCVKi7i03GePFMUmmfxBxBsQ6dA8CRU2wtDs+gz8U+RFceeYBVxtZu8+ou5lSObfsZkD5RnKVBBbXNfsvqwCqoTCgMdBBdbHYX57NWC068/jlVjqXHxZ2f1KjoAM/ikE763lKAEAAZqtDWaV0YRuEw4wNE2sLvKF9F4Fi77QzThy1lfVhhHVdsKh7yVVKSezphRsTj2LaaNy1vc4oUUqMBRSSCrD5mNJv7ee+AsnZ6Xij+4NH/kwd6v2E1Onz2c2cofU3RyFM86ZHRNVbvwcmzAHbMLfs6ufQ76AareIXUQ3IOifhgafMluWTfTb5KvOI2ctZLqHQYHP5cVYllRTwp+xkRwpYloeBpcdCb0ucUfvhgmbckp5qP7L8NYn7PZ49hmbFNcw+F4L1E/z1hq0dlzCZMVqWZLqAV1F9dq9JWOi2va2gy/EFJIRK4pCkVmtdtmnRWoOKNczkKnM+AwpenXWULEgzA3DUcMbaCeiK1Rg2IACrxXkxVMHdILQb0I4od7/AviSuLYEaziy0FsGdR32naBkgnWwpoytWhYvb/7PllwwSq2If+QSv04G8uZUpR/W45mvW64odzcL7iru6lRPp3byNkbPaaX6s1GvsLpxAb54SUmKfMCI/qSgUMqOAhCtQ8m4k92FIt9qeA420WEvgvnPiFXAOT36Owo36Z5g09AkuV1hZgLc/vy0SOwMTdUv3wLt9lYYdAEIDAIKk7KyOmz9XnKpDT4dSthmiqT0aKfH/7cw4HhpblplS/ogmds6hqGoIb7fRa3c7hc7RLffHc2g820sWHcuaP682e13JwgSZJk36Jz6dH0+slo5RB42RxiAC6v+YYF7dfDuLN8Ad3GlOPWvUdmQfBRnS5kGkvguhWmMCHTzdHU234l9ObIH6KxyVeRGyDwAuqTp1vF7JN06lwaPzr/yu5b/eos/98KlcPDM6cMxa07YsR4ziphA6YJgJcLJbegLSqusuoTckjf4LpM33bXXTpTFKsivON/R9CRaCn0/vTjWFCuRuRqDQTzgWPlRwhO7cuSYpR1nUGbQ+dFpz/Z/fL5EuAX4GRAE/LwzMLFruUjKNz8Fa/mJJyQT4QALQh0wdpJ8I9hwJpfZlNfv/T8oVKObC4VG7QvzALGMKX96Ag2b+QfarWFlTSTVUjuZ0TLs62GAV7TOuEIvYFGr6fT62ntuMRtVTA7PeeFC4ZHsP6bkm2ljNv7yh+WSdMXJOza/zPfnGfP3xbdIs1n0ZqSKKceLWNc6Jdkv7/heerFZT5Ft6cgUGGNWEuI5TH/4zURN9+pvEJI7uNXRzkXNTuOPr6059kDyIqGslz2iBjh9WVX4rnynsZIiuyNDBBCkBSQKSK2/t/RSv6mh2i0EJ1WT6PVX8BHPNkp4VfZWGNBCv49ZtBtWjGKrYhKhJdby+8800EvOaGGCKGRqUcGQ9AkRFPr7HWX6Jei6TOw+cMlNdQWw8QpM8aNHNvRWhX1e8vKvf5IU80Ii50iltB7XHKjCey55Qs8riiO3cG2xiHBJahU16Orej+lxECVb0x0jIb1qauV3G/yz3SDBj5fmCgD1jrHw1CR+Vp0UH8bPF+gIiehmbLViTE2eFpkX7bF1oPQTAStgVSpHDrhyspLhuIKrLisaF50AQBJ5S//+8j0kMvhr5t2bHumwXjqQdf7mzmNnC/EZTJIYdFDthKxFrImjxIwnxMdz6azxKdPK+EnStJb2WBet3KxXqrXz+0HfxhxKpOVmI5ft+En3dneEWw4KpGktPOuPdFrDjbUfbTSvUkzGAInI84ZhCYfoQ+ljzajcsbyOPYM2xrXMqSw8QxLQ+p3u3Kc0jFH008sjv2MXYkLy9R21VOivTtVK89o61F0EgwFYeVhdVJCR8zCpE9FmRzC2OOq0ccJHCbaLwrVTzk8+TD+8+rA6O+jnR6hQRozWz3DpcNZ+HGrTeO3ZYIyl85VVEBDSnHfnFo/htC+/tRiH24C1DX+0OX3oOHEjShM/HmxSZWepPk3q4TAyGQDLbOiV9iooMJlPPWyLepXtR31BtPFVJvD4osYBJu3NPnEpeDvVGKaRWWKQt8OpqsEm+6acr5AHDuHVcR17Fl7soJGDL7wG55sCZgtDleOpgYAZKBitZiUmEDMGOJLYPdF3seXFXg1l2Rm/jzeOt4M/vboYZPT9GytxJwiEsd2YqG4XMp2zAbDPWp4gICc2llrVtAyJQsU12W6klhR4RuSX/Az4gdTldABvyell61a1AMsMFZIpfXT5he+aOYdTYK9+PxMOLoqVW53DCkp87lldu5SP77BVmQrgWLsxOJBLYzs1kHVsRHREML1pnxQSC0Qj2RUU44Q02Uf//86z5v8NPhhqG+FaZ6StbvZfTZKLUrKyoLD+apydlLR7hgDra2ORIXTIvGwY4VFOY0d2V5tMa35fUe7ujo674/lRdgjj7fZ3tMFjqPecA7mTzZ5fuEU3Rs+ZhHbHlFezlPs14N2SFMOSJrErIkpzE9pMhs0FO/rve9g21LcWUtwlTbOtvkDdNEzX9Z54LpleBuwphQHjnpDJlfJBrIFfsUHCwkXXGkfU2Ri9jTNGCkQFUvGcnl7jnwrd1PdYltTmi+iQbrnWTeC9ABgz+3U1OpdLkqj4Ec2m8YtjUChodz73IS8OZLOFeLcEpNGU2K2qJ2cf6wn7zWL3lcUnV/079lmQvPtfzeVnR+j/Gsj93uJ4t2uKpkowmQ070r95jPd3afIAERJ0adc7Qlj3+gmvNHWcvclSr/9nyyvJBtB8cHyAIybOholoeGmCY8Ikx+N0GeaRRLVUU5+pZB8gczhh1O++cmi9dSAZbjtWor2h7j/+01dlfsLgLBzWENZM1nTWQSry1Ksq2aRis/YqIVJkkGD+lWxdVLdlb+0WOWd/+4KQIRlYGcyV2h+kPEsqunNotxYixbvu83Yv7RLDwnF4gydVHfvg8z7338nWkor/1zORc1XmIyedFJ/wpA8/1i4GLewVIykvgj2uQ/Et35P5HmkHtM2fORUj7bqqTtlNYn8FHCfRxu7QcG1q7UlISFUFqko/RaHxLEYNjPeQ2Nyp24vguzVaU+4xic+sg6wml34bsVV9ILXT71j0WZiKgqcZqdlcxy7hw3/UqBb9XpQ+kn1juAr/f4N72AsWIxxr+5h0UOfsN5MlsSRLlPUyIhuckEo/K207ej7NlpRRY5xkRaa1X20lsBUiRSAHUbGGvSgp1RlzPJDSJnB6mr7pR9kyOBpCvQPDPc2DbluLW36Oi92JGCZya2ft8OBKorRTz+qhti510Om+5gYmR/+1yhitmfPzTbNNaj0pQNDgX4D+lfVR/qoBUrM52g14Jxk30iHa3h5uU0b6fRFRufKHV5Xtk+HVJotSMSnz87yRzoL9kcG3EpM4IQ9k8ttmn4hXW6oriYoyyj8OiUluHXqxBevxNxps3mIDwQna6BS8dkEWf9sr23QiLxgeIzNOSLoAIZ5ay80zOtCH6e7scLHkWvwAZho95ALSmVbSX5aef6WG6oUAaNuKSXGOieDbaB6MKwTN7BdULGjbnHU4XM5kmxlhQ9dbje28IrkI8RtloitHi/osU6NTqtE7OhNwt82BA0EZ0zNS59wJ/YqfZwNo0aaxQDoLY0URsrAcshgqKnRbtkilAXyZqkBnRqsOVwe4Wv6Nk+xW4eWRku6x2eWh2xBcjBRWV4K5tfnVqkMAYcFjtRo/Uk8bhI+2vmQaOLrTxvgZQB36mQOZ+JABoGIT2KCk/sw8JxZPz49zZJqZX1s9B6uwIG34/XXbsnNuYcsUQG9CBIHVOOfMIcxGMOYnT9EWupQjor5ZE2AdXnFZQHo18AD1dI3MrJ0B662drRAnu3PRAYWxKoafMYyLbkQJgbTmzJl6YRYlS6vqLXA3FMedI4e6TrevCzafdn2FC84wzvZj1p1k/2mf2w6eFlKblLNIrx8IWtgoLiyOMTtznc08csBwh370WY3NdoiUqtdTr/L51K71Ag0oF63ZfFCHXE27LCMLvZhQyYXxDyO3txQxcCqyorGwe01GrH3LQEb5x4jKpAI5w2UJHNpQ9oSSER8AvwzoLapgAmIgWKwANkqrxvSmyOWeoKlNel/OujDcZiquVhaGBkVHr/98fgsXVEMKb4tIHSTo2p/SnotJ5aQ/1ujmPtTzoPvPQPiXp41UwJBlVXi8L4xU2dQhq4J7MY/6iX06fsmE+26RY4MQiUb8ZsiMm1eUQ4CB2BNJyBU/JQsHk8E7HLI6g5Cyn2tloVW1J1X0I65C9o8LaKVb3NjBe1anqycMIoGs01oADQHlQ+YstHgZpn82vUIuk6rXYci6//mXODxLnA6G4+LQTwdefkdbruxvp8pz1SuBSsL8nNcxtoRAh4OCUYW/kd/qiAbpCjR56DhMJrT3LmrzyYT+jfRv1XrH+KhS2p41Yy+3DUpwpF45I7S8Aif+Zuf5kUCvsI+ocel2anU0fBieKCPtoAz8Sa3rMReml6iBoNrlFLnBPjhR+CyJ6wp+uSFt+f7hqLe+X4c8N4mzL+98PmL4g/wDwDZhIOjRrnDOQWe/YSpNkmH3pztrQMLvy2e4LdadajDHB5ZOtS7XKvzgGXNke/1eXqc6kLZhzJcxUfyQXLSmPEMj3yGPZj0Pc8FE9ftGiOf5iEfP6nq5F8Sb7Jwi0PO1T/N/S3p7KcJ6RY/8fantiQcW5vCGUsxLYR8isdkJB3iriNvAEAGCflFilh6wud2FsCU5yXdapFTrnyng2TSwUjVV6EXqHtlwHTBRJ5P7P1om0UNpwft/XG6cVGTE2WOD4szWF+16SuzXSijq0FMYY9uw+niWA2G+61RcJMMZXMAGwT3V0tnK7ldfrLSJyrOXoH3H/CBVazyHHqIRg/SaXV0Wj1ugRhSldVBmrLTcWw8K1LS6N2fgfknKxRsNYRbP540IRgLrkxx5EGDElvdIXcqbujFLcs4ij6hWiHay1iRQWJsYFKkAqXqpUJRBsIFKqnmI1WY5AsTi8tTWr7oGDbWmMc+/WEF3Y+TUFZdypqVlnAhmJYmmi0Tr5RIuAr4rITZ4cWz8rDp2KzsQB1a2EBxUJqJuC2q+yr90pXydHaSw5fou3HnmOZBL4Z+o3SgFRCOuEm6XrfPraHt66LcAiIJNg/ejlTHjHaK6J+/TL6iaFtqTWVDRgKRsOI4Bd+HRGRX82VzxeLrGCVjiKR0Xh446sdCuEKhRJwbpzDWLZdRqr7uw3gUznCSggOqqlI5tz/SmBLVqOQzvoNJeCL+u7OJfROICfS3fJmOLwii6ZS0NEp6Jwn3fninejaQACBCdAWgOny7qlO3VxKrbh2f0GFo+LnuNp95Kh4MmsKRPw7qWwsaRlvKfFduJ74zwdyZgDs0FMxT8MftnvKfELjuiQcvyEfPaUyTnZYoNNMn8OEh01qhdCnrKfVdvwnFih9zn2HE6cS54VSmwUuXp86hOikUJ7XTPXCdsvekQyNAt0qEV1qRrW1Avr/ILRwiZckbshS9LJGVIIH7K3lf50zJrFItm/ob8ps0Q3RMJt8rob/73b3IbteiEarf5Hg62ELAKpsE4h3lsT417Zks9lEK8hTgL5J/LcIVdspXDwJc6T5Enowlo3QP5Nye6gQTkibyaigfjxg+LU5W8lM3UMmQmnMwI2M+La13x+abOGY8GzC4qiGXxX4lALtZxxH+tEarP/4z9N9SIejyQaYcLwQuRKy7nOF9Klf+ZiiviI8o7W6F3hnSvCCUVuxpzpTarodSlAfMWlL7ZzDzqhLvCO45ZTjKH6VWb6gwXycsdziVWqhE8gCfctoPeSxnR9dJjbqXbx9NF6qPZSsYTUxWI4PRyGI2ybuN5MqJZULlj0vwnPliYMqu25lnCB9A61KnqIXjn4tpbGnAomVg/wG6cWnjeYjagSm0qEdwZx++tWBPC0RtHPJYiqKJhGJvJq5mvEyTPlEOPHhwK2YRfkTWHhl08lMhAvLOn6FjXuVpZhPc1COCekHzkXEbcrqXun9KSxNIpUpUrarWoC54XsuwL56Djr91yNcDw4xqqXzpSTlCgSRXOzQjnf6QJ0uRyVKVgskVPD+XK+BwVwW2S6TSg1OosgyKlEqVUjJkO3G9vHAB/G+gkdSaFphZrvGwrwLHWFNzNH40Rn9CRyf46AV1QLRFp5Z8nKuiu0Ssi0zd4wBDcJmpWCbm7BYfUXr4K9usLI6VJZgkkQ4WS+qCN9Iy0poH9aHIxf69LCBzD+jKy1m/J3I9dJ+sGNqtlxxZp25mRcjt2h34SQHAkVJCQEIMLmUrqAYpWi0u1QrxbET/39h3ObiVAPxHxhUVDFvUMRWVSgWiRlWu28l+PgSW/pXQgoZZ1aUvt/89TR2xn/S3t0XopBnBHebtjp+o2zR7hroR8Ux+JSG/Zp+39oTbZ5c97ZyLGMwbhQAIcPjv+75Peu6fi6deAoAHHxfEAcCTf9YHJ3f9aPnuOG6QlQAIfqePbKWMPiycb9zv9HTVO03+S7CAJJKkQXxqbO1q3rU54FHbjSIr5ZeQipHEqPEoEFZUOGKqOHtKvCsFpRkzRgseZdk5LYKR9ImvNZ4kbahSSoKGHk5G3WofJum8knMahNQySVhQN4nhZiRJ5LtCPSJMo/gsgyTPZGo9OdDOMqUlXPV5hXstQ3Afw8TAko7GNRhrRv95wfdEY66wsYlzRovKBFFDpHNeScloUSgbwGssirFRjvgHvYWbWpoJognMt17jFg2AK6vxtimI39AfiezIK7uAjCVzBACACtn/D7P/PXZsesmDtALlsn0uPwjp0hJhs3zJQiBPPSiGgVK2AB/lkz3OeWiSjUHO/6fZRBEAbYyoav8/KOTBq0qE8++tbAPCDPMEgLn/MQhgutkEeqKhhhL6tnZGo+DEE5hc/WltUVCp2xJMBbWlZHvYlhZneVsWd2PbskXr2oYRQ9kVIgg4tyXAJ5C+PQXI/c1LLYv0Y10730CVLBAjixla2fZ7x6UqxAmXEs6MiplYihNiLSxpBzDqCteGwbZm+LrSbnXQj2OjI0twk0+vBOhioFDt/YZZ1bXuV647X73yNl/DYwWVMBGtGWivqHtF/VFRxyhcqIt4GdqZ788Qb+SQ+lqGtSmUvTrlM5uNsI6wohL9aqSA3TAo93XBtB0gsqVV5YxsfjNtnwc4pjZTxpnkL/oLM0BvioQrBi7dVVeQVBp6FIhorGibS+V/Ph1g1oqSrKiabpiW7bgeCioaOgYmFjYOLh4+ASERMQkpGTkFJRU1AAgC00CgtHT0DIwyZclmksPMIleefAWsEIygGE6QFM2wHC8AUZIVVdMN07JD+RxOl9vj9fmBjEzMLPIVKGRVpFiJUmXKVahUpVqNWnXqNWjUpFmLVoPRZLZYbXaHk7OLq5u7h6eXt49v7f5mTu0B7EIwgk5MdrOyFBVnmU6YIYmpSb8urww2h+1vyP45fvZDzyryf0afZXIjdwcB5EpSRATBExHHKEVFGE5MUlxRKZZZ0phhc8I7IZigZFAWQyYJYwTFcIKk6MmswTQKGQspA7YGmQyrALIjMUWFEIyoymhcmm8FUoUChGAExXCCDEvl0uly9oK7BBVU+gdSF7THzZPivybkZWp9W5uh/1hPUmVzW139v/Ywr2eTkXiCPvn/8NXOYS8aPsr/5YeSRh3pTUYzJqloxRQddpios/BQRsyoB2jkcrlaVAJs+9kCjVEsxvAxXbrfIpsil2amWdJy7dTAlklEgxyZa9pi9nuqWU9cmpJTig5TO39rCP/JK8IO3l+S+rM5il1B5C/8aWsbrMU/27CNGwcA';
  let fontReady;
  function loadFont() {
    if(!fontReady) {
      const face=new FontFace(family,Uint8Array.from(atob(fontData),ch=>ch.charCodeAt(0)));
      fontReady=face.load().then(loaded=>document.fonts.add(loaded)).catch(()=>{
        fontReady=null;
        throw Error('The Thai lettering font could not be opened on this phone.');
      });
    }
    return fontReady;
  }

  function shapedInk(text) {
    const canvas=document.createElement('canvas');
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    const font=em+'px "'+family+'"';
    ctx.font=font;
    const box=ctx.measureText(text), bodyHeight=ctx.measureText('ก').actualBoundingBoxAscent;
    const pad=8, baseline=Math.ceil(box.actualBoundingBoxAscent)+pad;
    const w=canvas.width=Math.ceil(box.actualBoundingBoxLeft+box.actualBoundingBoxRight)+2*pad;
    const h=canvas.height=baseline+Math.ceil(box.actualBoundingBoxDescent)+pad;
    ctx.font=font;ctx.direction='ltr';
    ctx.fillText(text,pad+box.actualBoundingBoxLeft,baseline);
    const rgba=ctx.getImageData(0,0,w,h).data;
    return {mask:Uint8Array.from({length:w*h},(_,i)=>rgba[4*i+3]>=128),w,h,baseline,bodyHeight};
  }

  // Guo-Hall thinning preserves the openings in traditional Thai letters.
  function thin(mask,w) {
    const del=[],n=mask.length;
    let changed;
    do {
      changed=false;
      for(let pass=0;pass<2;pass++) {
        for(let i=w+1;i<n-w-1;i++)if(mask[i]){
          const t=mask[i-w],tr=mask[i-w+1],r=mask[i+1],br=mask[i+w+1],
            b=mask[i+w],bl=mask[i+w-1],l=mask[i-1],tl=mask[i-w-1];
          if((!t&&(tr||r))+(!r&&(br||b))+(!b&&(bl||l))+(!l&&(tl||t))!==1)continue;
          const neighbors=Math.min((tl||t)+(tr||r)+(br||b)+(bl||l),(t||tr)+(r||br)+(b||bl)+(l||tl));
          if(neighbors<2 || neighbors>3)continue;
          if(pass ? (t||tr||!br)&&r : (b||bl||!tl)&&l)continue;
          del.push(i);
        }
        if(del.length)changed=true;
        for(const i of del)mask[i]=0;
        del.length=0;
      }
    }while(changed);
  }

  function components(mask,w) {
    const groups=[],owner=new Uint16Array(mask.length),links=new Map();
    const xy=i=>[i%w,Math.floor(i/w)];
    for(let i=0;i<mask.length;i++)if(mask[i]){
      const out=[];
      for(const [dx,dy] of [[-1,0],[1,0],[0,-1],[0,1],[-1,-1],[-1,1],[1,-1],[1,1]]){
        const j=i+dx+w*dy;
        if(mask[j] && !(dx && dy && (mask[i+dx] || mask[i+w*dy])))out.push(j);
      }
      links.set(i,out);
    }
    for(const first of links.keys())if(!owner[first]){
      const id=groups.length+1, ids=[first];owner[first]=id;
      for(let k=0;k<ids.length;k++)for(const j of links.get(ids[k]))if(!owner[j]){owner[j]=id;ids.push(j);}
      const points=ids.map(xy),ys=points.map(p=>p[1]);
      groups.push({id,ids,points,top:Math.min(...ys),bottom:Math.max(...ys)});
    }
    return {groups,owner,links,xy};
  }

  // Measure the radius of the largest clear circle inside each stroke loop.
  // A four-connected flood respects the diagonal links of the skeleton.
  function smallestOpening(mask,w,h) {
    const dist=Float32Array.from(mask,v=>v?0:65535),diag=Math.SQRT2;
    for(let i=w+1;i<dist.length-w-1;i++)dist[i]=Math.min(dist[i],1+dist[i-w],1+dist[i-1],diag+dist[i-w-1],diag+dist[i-w+1]);
    for(let i=dist.length-w-2;i>=w+1;i--)dist[i]=Math.min(dist[i],1+dist[i+w],1+dist[i+1],diag+dist[i+w-1],diag+dist[i+w+1]);
    const seen=mask.slice();let smallest=Infinity;
    for(let i=w+1;i<seen.length-w-1;i++)if(!seen[i]){
      const cells=[i];let outside=false,radius=0;seen[i]=1;
      for(let k=0;k<cells.length;k++){
        const p=cells[k],x=p%w,y=Math.floor(p/w);
        if(x<2 || x>=w-2 || y<2 || y>=h-2){outside=true;continue;}
        radius=Math.max(radius,dist[p]);
        for(const q of [p-w,p+w,p-1,p+1])if(!seen[q]){seen[q]=1;cells.push(q);}
      }
      if(!outside && cells.length>5)smallest=Math.min(smallest,2*radius);
    }
    return smallest;
  }

  // Each disconnected letter or accent branches from the surrounding frame.
  // A straight approach has to be visible from its edge in the actual image;
  // an upper mark can never acquire a stem through the vowel below it.
  function exits(graph,w,h,baseline,bodyHeight,rim,clear) {
    const {groups,owner}=graph,[left,top,right,bottom]=rim;
    const links=[],radius=em*.10;
    const low=new Uint16Array(w),high=new Uint16Array(w).fill(h);
    const west=new Uint16Array(h).fill(w),east=new Uint16Array(h);
    for(const part of groups)for(const [x,y] of part.points) {
      low[x]=Math.max(low[x],y);high[x]=Math.min(high[x],y);
      west[y]=Math.min(west[y],x);east[y]=Math.max(east[y],x);
    }
    const sorted=groups.map(part=>{
      const above=part.bottom<baseline-.82*bodyHeight,below=part.top>baseline-.06*bodyHeight;
      return {...part,above,below};
    }).sort((a,b)=>Number(b.above||b.below)-Number(a.above||a.below));
    for(const part of sorted){
      let best=null;
      const sidePenalty=bodyHeight*(part.above || part.below ? .12 : .72);
      for(const id of part.ids){
        const [x,y]=graph.xy(id);
        const options=[
          {side:0,edge:y===high[x],q:[x,top],penalty:part.above?0:bodyHeight},
          {side:2,edge:y===low[x],q:[x,bottom],penalty:part.above?Infinity:0},
          {side:1,edge:x===east[y],q:[right,y],penalty:sidePenalty},
          {side:3,edge:x===west[y],q:[left,y],penalty:sidePenalty}
        ];
        for(const {side,edge,q,penalty} of options) {
          if(!edge || (side===0 && part.below) || (side===2 && part.above))continue;
          const vertical=side%2===0;
          if(vertical ? x<left+radius || x>right-radius : y<top+radius || y>bottom-radius)continue;
          const len=Math.abs(q[0]-x)+Math.abs(q[1]-y);
          const score=len+penalty;
          if(best && score>=best.score)continue;
          const dx=Math.sign(q[0]-x),dy=Math.sign(q[1]-y);
          let free=true;
          for(let step=0;step<=len && free;step+=2){
            const a=x+dx*step,b=y+dy*step;
            for(let off=-clear;off<=clear && free;off++){
              const xx=Math.round(a+dy*off),yy=Math.round(b+dx*off);
              if(xx<0 || xx>=w || yy<0 || yy>=h)continue;
              const other=owner[yy*w+xx];if(other && other!==part.id)free=false;
            }
            for(const prev of links){
              const nx=Math.max(prev.xlo-a,0,a-prev.xhi),ny=Math.max(prev.ylo-b,0,b-prev.yhi);
              if(Math.hypot(nx,ny)<clear)free=false;
            }
          }
          if(free)best={score,id,side,q,xlo:Math.min(x,q[0]),xhi:Math.max(x,q[0]),ylo:Math.min(y,q[1]),yhi:Math.max(y,q[1])};
        }
      }
      if(!best)return null;
      links.push(best);
    }
    return links;
  }

  function simplify(points,epsilon) {
    const keep=new Uint8Array(points.length);keep[0]=keep[points.length-1]=1;
    const stack=[[0,points.length-1]];
    while(stack.length){
      const [lo,hi]=stack.pop(),[x,y]=points[lo],dx=points[hi][0]-x,dy=points[hi][1]-y,n=dx*dx+dy*dy;
      let far=-1,distance=epsilon;
      for(let i=lo+1;i<hi;i++){
        const a=points[i][0]-x,b=points[i][1]-y,t=n?Math.max(0,Math.min(1,(a*dx+b*dy)/n)):0;
        const d=Math.hypot(a-t*dx,b-t*dy);if(d>distance){far=i;distance=d;}
      }
      if(far>=0){keep[far]=1;stack.push([lo,far],[far,hi]);}
    }
    return points.filter((_,i)=>keep[i]);
  }

  function walk(graph,entry) {
    const stack=[entry],trail=[entry],edges=new Set();
    while(stack.length) {
      const p=stack.at(-1);
      let next;
      for(const q of graph.links.get(p)){
        const key=Math.min(p,q)*graph.owner.length+Math.max(p,q);
        if(!edges.has(key)){edges.add(key);next=q;break;}
      }
      if(next!==undefined){stack.push(next);trail.push(next);}
      else {stack.pop();if(stack.length)trail.push(stack.at(-1));}
    }
    return simplify(trail.map(graph.xy),.55);
  }

  function framedWord(graph,attachments,rim) {
    const [l,t,r,b]=rim,round=em*.10;
    const corners=[[r-round,t+round],[r-round,b-round],[l+round,b-round],[l+round,t+round]];
    const path=[[l+round,t]];
    for(let side=0;side<4;side++){
      const axis=side%2, sign=side<2?1:-1;
      for(const link of attachments.filter(k=>k.side===side).sort((a,b)=>sign*(a.q[axis]-b.q[axis]))) {
        path.push(link.q,...walk(graph,link.id),link.q);
      }
      const [cx,cy]=corners[side];
      for(let j=0;j<=8;j++){
        const a=(side-1+j/8)*Math.PI/2;path.push([cx+round*Math.cos(a),cy+round*Math.sin(a)]);
      }
    }
    path.push(path[0]);
    return path;
  }

  async function design(text,{groove}={}) {
    if(!Number.isFinite(groove) || groove<=0)throw Error('This garden is missing its groove width.');
    const label=typeof text==='string'?text.trim().replace(/\s+/gu,' '):'';
    if(!label || !/^[ก-ฮะ-ฺเ-๎๐-๙ ]+$/u.test(label) || /(?:^|[^ก-ฮัิ-ฺ็-๎])[ัิ-ฺ็-๎]/u.test(label))
      throw Error('Enter Thai letters with their marks attached to a letter.');
    const small='These marks would run together in the sand. Try a shorter Thai name.';
    const failure=reason=>({label,path:[],lines:[label],legible:false,reason});
    if(label.length>40)return failure(small);
    await loadFont();
    const {mask,w,h,bodyHeight,baseline}=shapedInk(label);
    if(!w || !h || bodyHeight/Math.hypot(w,h)*2/groove<3.5)return failure(small);
    thin(mask,w);
    const graph=components(mask,w);
    if(!graph.groups.length)return failure(small);
    const points=graph.groups.flatMap(c=>c.points);
    const extent=axis=>points.reduce(([lo,hi],p)=>[Math.min(lo,p[axis]),Math.max(hi,p[axis])],[Infinity,-Infinity]);
    const [x0,x1]=extent(0),[y0,y1]=extent(1),pad=em*.080;
    const rim=[x0-pad,y0-pad,x1+pad,y1+pad];
    const cx=(x0+x1)/2,cy=(y0+y1)/2;
    const scale=.97/Math.hypot((rim[2]-rim[0])/2,(rim[3]-rim[1])/2);
    const sourceGroove=groove/scale,xHeightGrooves=bodyHeight/sourceGroove;
    const minimumGrooves=5;
    if(xHeightGrooves<minimumGrooves || smallestOpening(mask,w,h)<1.46*sourceGroove)return failure(small);
    const groups=graph.groups;
    for(const part of groups){
      const xs=part.points.map(p=>p[0]);
      if(Math.hypot(Math.max(...xs)-Math.min(...xs),part.bottom-part.top)<1.6*sourceGroove)return failure(small);
    }
    let minimumGap=Infinity;
    for(let i=0;i<groups.length;i++)for(let j=0;j<i;j++)
      for(const a of groups[i].points)for(const b of groups[j].points){
        const d=(a[0]-b[0])**2+(a[1]-b[1])**2;if(d<minimumGap)minimumGap=d;
      }
    if(Math.sqrt(minimumGap)<1.32*sourceGroove)return failure(small);
    const attachments=exits(graph,w,h,baseline,bodyHeight,rim,Math.max(2,Math.ceil(sourceGroove*1.15)));
    if(!attachments)return failure('There is no clear way to reach each mark in this space. Try a shorter Thai name.');
    const path=framedWord(graph,attachments,rim).map(([x,y])=>[(x-cx)*scale,(cy-y)*scale]);
    if(path.length>8000)return failure(small);
    return {label,path,lines:[label],xHeightGrooves,minimumGrooves,legible:true};
  }
  return {design};
})();
