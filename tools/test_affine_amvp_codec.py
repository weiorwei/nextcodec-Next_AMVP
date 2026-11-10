#!/usr/bin/env python3
"""Finite codec regression for the independent affine TMR-Lite modes.

Run baseline BEFORE rebuilding, using copied old binaries; then validate after
building. All bitstreams, generated YUVs and logs are placed in --output-dir.
Only the compact validation JSON is written to the chosen project report path.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TRANSLATION_MODES = ['-3', '-2', '-1', '0', '1', '2', '3', '4', '5', '6', '7', '8', '3.1', '4.1', '5.1', '6.1']
REAL = Path('/ssddata1/testsequence/classD/RaceHorses_416x240_30.yuv')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def assert_equal(a, b):
    if sha(a) != sha(b):
        raise AssertionError(f'Files differ: {a} != {b}')


def generate_input(output):
    """Analytic piecewise affine motion; no external image asset is needed."""
    width, height, count = 192, 128, 8
    path = output / 'piecewise_affine_192x128_8f.yuv'
    rng = np.random.default_rng(4302)
    raw = rng.uniform(0, 255, (512, 512))
    texture = sum(np.roll(np.roll(raw, dy, axis=0), dx, axis=1)
                  for dx in range(3) for dy in range(3)) / 9
    yy, xx = np.mgrid[:512, :512]
    texture = np.clip(texture + 35*np.sin(xx*.41) + 27*np.cos(yy*.23) + 19*np.sin((xx+yy)*.16), 0, 255)
    y, x = np.mgrid[:height, :width]
    zone_x = (x >= width//2).astype(float)
    zone_y = (y >= height//2).astype(float)
    with path.open('wb') as stream:
        for frame in range(count):
            time = frame + .14*frame*frame
            angle = (.006 + .004*zone_x - .011*zone_y)*time
            u = 90 + (x-width/2)*(1+.003*time) - angle*(y-height/2) + time*(.6+zone_x)
            v = 90 + (y-height/2)*(1-.0015*time) + angle*(x-width/2) + time*(.3-.9*zone_y)
            ix, iy = np.floor(u).astype(int), np.floor(v).astype(int)
            fx, fy = u-ix, v-iy
            luma = ((1-fx)*(1-fy)*texture[iy%512,ix%512] + fx*(1-fy)*texture[iy%512,(ix+1)%512]
                    +(1-fx)*fy*texture[(iy+1)%512,ix%512] + fx*fy*texture[(iy+1)%512,(ix+1)%512])
            stream.write(np.clip(np.rint(luma), 0, 255).astype('uint8').tobytes())
            stream.write(np.full((height//2,width//2), 128, dtype='uint8').tobytes())
            stream.write(np.full((height//2,width//2), 128, dtype='uint8').tobytes())
    return path


class Validation:
    def __init__(self, args):
        self.output = args.output_dir.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.input = self.output/'piecewise_affine_192x128_8f.yuv'
        self.report = args.report.resolve()

    def run(self, command, name, success=True):
        stem = self.output/name
        log_path, err_path = Path(str(stem)+'.log'), Path(str(stem)+'.err')
        with log_path.open('wb') as log, err_path.open('wb') as err:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=err, timeout=600)
        record = {'command':command,'log':str(log_path),
                  'stderr':str(err_path),'exit':result.returncode}
        if success != (result.returncode == 0):
            raise AssertionError(f'Command exit {result.returncode}: {name}\n'
                                 +err_path.read_text()[-2200:])
        return record

    def command(self, stem, affine='0', translation='0', before=False, frames=3,
                config='ldp', trace=0, affine_type=None, amvr_opt=None,
                hash_me=False, real=False, rpr=False, extra=()):
        app = self.output/'EncoderAppStatic.before' if before else ROOT/'bin/EncoderAppStatic'
        cfg = 'cfg/encoder_lowdelay_P_nextRt500.cfg' if config == 'ldp' else 'cfg/encoder_randomaccess_nextRt500.cfg'
        cmd = [str(app),'-c',cfg]
        if real:
            cmd += ['-c','cfg/per-sequence/RaceHorses.cfg','-i',str(REAL)]
        else:
            cmd += ['-i',str(self.input),'--SourceWidth=192','--SourceHeight=128','--FrameRate=30','--InputBitDepth=8']
        cmd += ['-f',str(frames),'-q','27','--TemporalFilter=0','--GOPBasedRPR=0',
                '--SEIDecodedPictureHash=1',f'--AmvpTrace={trace}',f'--amvpmode={translation}',
                '-b',str(stem)+'.bin','-o',str(stem)+'.yuv']
        if not before:
            cmd += [f'--AffineAmvpMode={affine}']
        if affine_type is not None:
            cmd += ['--Affine=1','--AdaptBypassAffineMe=0',f'--AffineType={affine_type}']
        if amvr_opt is not None:
            cmd += [f'--AffineAmvrEncOpt={amvr_opt}']
        if hash_me:
            cmd += ['--HashME=1']
        if rpr:
            cmd += ['--RPR=1','--RPRFunctionalityTesting=1','--RPRSwitchingSegmentSize=1',
                    '--RPRSwitchingResolutionOrderList=0,3','--RPRSwitchingQPOffsetOrderList=0,0',
                    '--ScalingRatioHor=2','--ScalingRatioVer=2']
        return cmd + list(extra)

    def baseline(self, mode):
        name = f'before_trans_{mode}'
        stem = self.output/name
        command = self.command(stem, translation=mode, before=True)
        record = self.run(command, name)
        print(f'baseline translation {mode}: PASS', flush=True)
        return record

    def decode(self, name, affine, translation, frames):
        stem = self.output/name
        record = self.run([str(ROOT/'bin/DecoderAppStatic'),f'--AffineAmvpMode={affine}',
                           f'--amvpmode={translation}','--UpscaledOutput=2','-b',str(stem)+'.bin',
                           '-o',str(stem)+'_dec.yuv'], name+'_dec')
        text = Path(record['log']).read_text()
        if text.count('(OK)') != frames or re.search(r'ERROR|MISMATCH|NOT OK',text):
            raise AssertionError(f'Decoded frame hash mismatch: {name}')
        assert_equal(str(stem)+'.yuv',str(stem)+'_dec.yuv')
        return record

    def regression(self, mode):
        name = f'after_trans_{mode}'
        stem = self.output/name
        encoded = self.run(self.command(stem,translation=mode),name)
        prior = self.output/f'before_trans_{mode}'
        assert_equal(str(stem)+'.bin',str(prior)+'.bin')
        assert_equal(str(stem)+'.yuv',str(prior)+'.yuv')
        if mode.startswith('-'):
            assert_equal(str(stem)+'_amvp.bin',str(prior)+'_amvp.bin')
        decoded = self.decode(name,'0',mode,3)
        print(f'affine OFF / translation {mode} byte regression: PASS',flush=True)
        return {'translation_mode':mode,'affine_mode':'0','bitstream_equal':True,
                'reconstruction_equal':True,'decoded_hash_frames':3,'commands':[encoded,decoded]}

    def smoke(self, affine, suffix, **kwargs):
        name = f'affine_{affine}_{suffix}'
        stem = self.output/name
        record = self.run(self.command(stem,affine=affine,**kwargs),name)
        decoded = self.decode(name,affine,kwargs.get('translation','0'),kwargs.get('frames',3))
        text = Path(record['log']).read_text()
        rows = [line for line in text.splitlines() if line.startswith('[AFFINE-AMVP-MVD]')]
        for line in rows:
            if f'MODE={affine} ' not in line or not re.search(r' IDX=[01]/2 ',line):
                raise AssertionError('Invalid affine mode or non-two-candidate index')
        if not kwargs.get('trace',0) and '[AMVP-' in text:
            raise AssertionError('Trace-off emitted translational diagnostics')
        if not kwargs.get('trace',0) and rows:
            raise AssertionError('Trace-off emitted affine diagnostics')
        if not kwargs.get('translation','0').startswith('-') and Path(str(stem)+'_amvp.bin').exists():
            raise AssertionError('Unexpected affine sidecar')
        models = sorted(set(re.findall(r' MODEL=(\d+) ', '\n'.join(rows))))
        precisions = sorted(set(re.findall(r' IMV=(\d+) ', '\n'.join(rows))))
        zero_l1_rows = sum(' L1_ZERO=yes ' in line for line in rows)
        print(f'{name}: PASS; final affine rows={len(rows)}, models={models}, imv={precisions}',flush=True)
        return {'name':name,'affine_mode':affine,'translation_mode':kwargs.get('translation','0'),
                'decoded_hash_frames':kwargs.get('frames',3),'reconstruction_equal':True,
                'affine_final_rows':len(rows),'models':models,'imv':precisions,'zero_l1_rows':zero_l1_rows,
                'commands':[record,decoded]}

    def parser_checks(self):
        results=[]
        for app in ['EncoderAppStatic','DecoderAppStatic']:
            for value in ['32','42','3.20','3.2junk','1','nan']:
                name=f'parse_{app}_{value}'
                if app.startswith('Encoder'):
                    cmd=self.command(self.output/'must_not_encode',affine=value)
                else:
                    cmd=[str(ROOT/'bin'/app),f'--AffineAmvpMode={value}','-b',
                         str(self.output/'affine_3.2_ldp_trace0.bin')]
                record=self.run(cmd,name,success=False)
                message=Path(record['log']).read_text()+Path(record['stderr']).read_text()
                if 'AffineAmvpMode must be' not in message:
                    raise AssertionError('Invalid affine label was not explicitly rejected')
                results.append(record)
        return results

    def validate(self):
        report={'status':'PASS','temporary_artifacts':str(self.output),'regression':[], 'affine_modes':[]}
        with ThreadPoolExecutor(max_workers=2) as executor:
            report['regression']=list(executor.map(self.regression,TRANSLATION_MODES))
        def validate_affine(affine):
            records=[]
            cases=[('ldp_trace0',{'trace':0,'frames':4,'affine_type':1}),
                   ('ldp_trace1',{'trace':1,'frames':4,'affine_type':1}),
                   ('four_param',{'trace':1,'frames':6,'affine_type':0}),
                   ('no_amvr_opt',{'trace':1,'frames':4,'affine_type':1,'amvr_opt':0}),
                   ('ra_bcw',{'trace':1,'frames':8,'affine_type':1,'config':'ra'}),
                   ('hash',{'trace':1,'frames':4,'affine_type':1,'hash_me':True}),
                   ('rpr',{'trace':1,'frames':8,'affine_type':1,'rpr':True}),
                   ('translation_3.1',{'trace':1,'frames':4,'affine_type':1,'translation':'3.1'}),
                   ('translation_oracle',{'trace':1,'frames':3,'affine_type':1,'translation':'-1'}),
                   ('racehorses',{'trace':1,'frames':6,'affine_type':1,'real':True})]
            for suffix,kwargs in cases:
                records.append(self.smoke(affine,suffix,**kwargs))
            assert_equal(self.output/f'affine_{affine}_ldp_trace0.bin',self.output/f'affine_{affine}_ldp_trace1.bin')
            assert_equal(self.output/f'affine_{affine}_ldp_trace0.yuv',self.output/f'affine_{affine}_ldp_trace1.yuv')
            if not any(r['affine_final_rows']>0 for r in records):
                raise AssertionError(f'No final coded affine AMVP blocks for {affine}')
            return records
        with ThreadPoolExecutor(max_workers=2) as executor:
            for records in executor.map(validate_affine,['3.2','4.2']):
                report['affine_modes'].extend(records)
        report['parser_checks']=self.parser_checks()
        report['trace_bitstream_equal']=True
        report['encoder_sha256']=sha(ROOT/'bin/EncoderAppStatic')
        report['decoder_sha256']=sha(ROOT/'bin/DecoderAppStatic')
        report['baseline_encoder_sha256']=sha(self.output/'EncoderAppStatic.before')
        report['input_sha256']=sha(self.input)
        self.report.parent.mkdir(parents=True,exist_ok=True)
        self.report.write_text(json.dumps(report,indent=2)+'\n')
        print(f'ALL codec checks PASS; report: {self.report}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['generate','baseline','smoke','validate'])
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--report',type=Path,default=ROOT/'mode_analyse/affine_tmr_validation.json')
    parser.add_argument('--only-modes',help='Optional comma-separated translation modes for baseline capture')
    args=parser.parse_args()
    validation=Validation(args)
    if args.phase=='generate':
        print(generate_input(validation.output))
    elif args.phase=='baseline':
        if not validation.input.exists():
            generate_input(validation.output)
        modes=args.only_modes.split(',') if args.only_modes else TRANSLATION_MODES
        if any(mode not in TRANSLATION_MODES for mode in modes):
            raise SystemExit('Unsupported baseline translation mode')
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(validation.baseline,modes))
        manifest=validation.output/'baseline_manifest.json'
        merged={}
        for record in (json.loads(manifest.read_text()) if manifest.exists() else [])+results:
            key=next(arg for arg in record['command'] if arg.startswith('--amvpmode='))
            merged[key]=record
        manifest.write_text(json.dumps(list(merged.values()),indent=2)+'\n')
    elif args.phase=='smoke':
        for mode in ['3.2','4.2']:
            validation.smoke(mode,'early',trace=1,frames=4,affine_type=1)
    else:
        validation.validate()
