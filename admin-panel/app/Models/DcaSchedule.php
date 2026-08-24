<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class DcaSchedule extends Model
{
    protected $connection = 'exchange';
    protected $table = 'dca_schedules';
    public $timestamps = false;
    protected $guarded = ['*'];
}
